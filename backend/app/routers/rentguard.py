from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from app.db.session import get_db
from app.db.models import Analysis, RentScenario, DailyRevenue, FixedCost
from app.schemas.rentguard import (
    RentImpactInput,
    RentImpactResponse,
    RentImpactMetrics,
    RentImpactExplanation
)
from app.services.cashflow_engine import CashFlowEngine
from app.services.rent_engine import RentEngine
from app.services.llm_router import LLMRouter
from app.services.cache import CacheService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rentguard", tags=["rentguard"])


@router.post("/impact", response_model=RentImpactResponse)
async def analyze_rent_impact(
    input_data: RentImpactInput,
    db: Session = Depends(get_db)
):
    """
    Analyze impact of rent increase on existing analysis
    
    Simulates the effect of a rent change on cash flow metrics
    and risk state. Requires either increase_pct or new_rent.
    """
    try:
        # Validate input
        if input_data.increase_pct is None and input_data.new_rent is None:
            raise HTTPException(
                status_code=400,
                detail="Must provide either increase_pct or new_rent"
            )
        
        # Get base analysis
        analysis = db.query(Analysis).filter(
            Analysis.id == input_data.analysis_id
        ).first()
        
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")
        
        # Get fixed costs
        fixed_costs = analysis.fixed_costs
        if not fixed_costs:
            raise HTTPException(status_code=400, detail="Analysis has no fixed costs")
        
        fixed_costs_dict = {
            "rent": fixed_costs.rent,
            "payroll": fixed_costs.payroll,
            "other": fixed_costs.other,
            "cash_on_hand": fixed_costs.cash_on_hand
        }
        
        # Get daily revenues and recompute current metrics
        daily_revenues = (
            db.query(DailyRevenue)
            .filter(DailyRevenue.analysis_id == input_data.analysis_id)
            .all()
        )
        
        revenue_list = [{"date": dr.date, "revenue": dr.revenue} for dr in daily_revenues]
        current_metrics = CashFlowEngine.compute_metrics(revenue_list, fixed_costs_dict)
        
        # Simulate rent impact
        impact_metrics = RentEngine.simulate_rent_impact(
            current_metrics,
            fixed_costs_dict,
            increase_pct=input_data.increase_pct,
            new_rent=input_data.new_rent
        )
        
        # Create rent scenario record
        scenario = RentScenario(
            analysis_id=input_data.analysis_id,
            increase_pct=input_data.increase_pct,
            new_rent=impact_metrics["new_rent"],
            effective_date=input_data.effective_date,
            delta_monthly=impact_metrics["delta_monthly"],
            new_risk_state=impact_metrics["new_risk_state"]
        )
        db.add(scenario)
        db.commit()
        db.refresh(scenario)
        
        logger.info(f"Created rent scenario {scenario.id} for analysis {input_data.analysis_id}")
        
        # Get LLM explanation (with caching)
        cache_key = LLMRouter.generate_cache_key(
            {"impact": impact_metrics, "analysis_id": input_data.analysis_id},
            "deepseek-v3"
        )
        
        cached_explanation = CacheService.get_llm_output(db, cache_key)
        
        if cached_explanation:
            explanation_dict = cached_explanation
        else:
            explanation_dict = await LLMRouter.call_deepseek_v3(
                impact_metrics,
                {"business_name": analysis.business_name}
            )
            CacheService.set_llm_output(db, cache_key, "deepseek-v3", explanation_dict)
        
        # Build response
        return RentImpactResponse(
            scenario_id=scenario.id,
            analysis_id=input_data.analysis_id,
            metrics=RentImpactMetrics(**impact_metrics),
            explanation=RentImpactExplanation(**explanation_dict),
            created_at=scenario.created_at.isoformat()
        )
        
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in analyze_rent_impact: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/scenarios/{analysis_id}")
async def list_scenarios(
    analysis_id: int,
    db: Session = Depends(get_db)
):
    """
    List all rent scenarios for an analysis
    
    Returns all simulated rent scenarios for a given analysis
    """
    # Verify analysis exists
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Get scenarios
    scenarios = (
        db.query(RentScenario)
        .filter(RentScenario.analysis_id == analysis_id)
        .order_by(RentScenario.created_at.desc())
        .all()
    )
    
    return [
        {
            "scenario_id": s.id,
            "created_at": s.created_at.isoformat(),
            "increase_pct": s.increase_pct,
            "new_rent": s.new_rent,
            "delta_monthly": s.delta_monthly,
            "new_risk_state": s.new_risk_state,
            "effective_date": s.effective_date.isoformat() if s.effective_date else None
        }
        for s in scenarios
    ]
