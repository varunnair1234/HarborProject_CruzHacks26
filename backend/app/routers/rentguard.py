from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import json
from app.db.session import get_db
from app.db.models import Analysis, RentScenario, DailyRevenue
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
        
        # Defensive defaults: treat missing numeric fields as 0.0
        fixed_costs_dict = {
            "rent": float(fixed_costs.rent or 0.0),
            "payroll": float(fixed_costs.payroll or 0.0),
            "other": float(fixed_costs.other or 0.0),
            "cash_on_hand": float(fixed_costs.cash_on_hand or 0.0),
        }

        # RentGuard requires a current rent value to simulate a change
        if fixed_costs_dict["rent"] <= 0:
            raise HTTPException(
                status_code=400,
                detail="Analysis fixed costs missing a valid rent amount"
            )
        
        # Get daily revenues and recompute current metrics
        daily_revenues = (
            db.query(DailyRevenue)
            .filter(DailyRevenue.analysis_id == input_data.analysis_id)
            .all()
        )

        if not daily_revenues:
            raise HTTPException(
                status_code=400,
                detail="Analysis has no daily revenue history to analyze"
            )

        revenue_list = [{"date": dr.date, "revenue": dr.revenue} for dr in daily_revenues]
        current_metrics = CashFlowEngine.compute_metrics(revenue_list, fixed_costs_dict)
        
        # Use effective_date year when available; otherwise use current year
        year_for_baseline = input_data.effective_date.year if input_data.effective_date else datetime.utcnow().year

        impact_metrics = RentEngine.simulate_rent_impact(
            current_metrics,
            fixed_costs_dict,
            increase_pct=input_data.increase_pct,
            new_rent=input_data.new_rent,
            year=year_for_baseline,
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
            # Some caches return serialized JSON strings — normalize to dict
            if isinstance(explanation_dict, str):
                try:
                    explanation_dict = json.loads(explanation_dict)
                except Exception:
                    explanation_dict = {"summary": str(explanation_dict)}
        else:
            try:
                explanation_dict = await LLMRouter.call_deepseek_v3(
                    impact_metrics,
                    {"business_name": analysis.business_name}
                )
                CacheService.set_llm_output(db, cache_key, "deepseek-v3", explanation_dict)
            except Exception as llm_err:
                logger.warning(f"LLM explanation failed, using deterministic fallback: {llm_err}")
                explanation_dict = None

        # If LLM failed or didn't provide data, use deterministic fallback
        if not explanation_dict or not isinstance(explanation_dict, dict):
            # Deterministic fallback explanation (keeps endpoint reliable)
            old_rent = impact_metrics.get("current_rent") or impact_metrics.get("old_rent")
            new_rent = impact_metrics.get("new_rent")
            delta_monthly = impact_metrics.get("delta_monthly")
            new_risk_state = impact_metrics.get("new_risk_state")
            runway_impact_days = impact_metrics.get("runway_impact_days")

            runway_line = ""
            if isinstance(runway_impact_days, (int, float)):
                runway_line = f" This changes your runway by {runway_impact_days:+.0f} days."

            explanation_dict = {
                "summary": f"Rent change from ${old_rent:,.0f} to ${new_rent:,.0f} increases fixed costs by ${delta_monthly:,.0f}/mo and moves risk state to '{new_risk_state}'.{runway_line}",
                "key_drivers": [
                    f"Monthly rent delta: ${delta_monthly:,.0f}",
                    f"New risk state: {new_risk_state}",
                ],
                "recommended_actions": [
                    "Review lease terms and effective date.",
                    "Consider negotiating the increase if it exceeds comparable market norms.",
                    "If runway decreases materially, reduce other fixed costs or increase near-term revenue.",
                ],
            }

        # Normalize LLM response: map 'concerns' -> 'key_drivers', 'recommendations' -> 'recommended_actions'
        if "concerns" in explanation_dict and "key_drivers" not in explanation_dict:
            explanation_dict["key_drivers"] = explanation_dict.pop("concerns")
        if "recommendations" in explanation_dict and "recommended_actions" not in explanation_dict:
            explanation_dict["recommended_actions"] = explanation_dict.pop("recommendations")

        # Ensure required fields exist with defaults
        if "key_drivers" not in explanation_dict:
            explanation_dict["key_drivers"] = ["Rent increase impact on fixed costs"]
        if "recommended_actions" not in explanation_dict:
            explanation_dict["recommended_actions"] = ["Review your budget and negotiate if possible"]
        if "summary" not in explanation_dict:
            explanation_dict["summary"] = "Rent increase impact analysis completed."

                # RentEngine may return additional fields over time; filter to schema-supported keys
        try:
            allowed_metric_keys = set(RentImpactMetrics.model_fields.keys())  # Pydantic v2
        except AttributeError:
            allowed_metric_keys = set(RentImpactMetrics.__fields__.keys())    # Pydantic v1

        metrics_payload = {k: v for k, v in impact_metrics.items() if k in allowed_metric_keys}

        return RentImpactResponse(
            scenario_id=scenario.id,
            analysis_id=input_data.analysis_id,
            metrics=RentImpactMetrics(**metrics_payload),
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
