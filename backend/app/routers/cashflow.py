from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import logging

from app.db.session import get_db
from app.db.models import Analysis, DailyRevenue, FixedCost
from app.schemas.cashflow import (
    FixedCostsInput,
    CashFlowAnalysisResponse,
    CashFlowMetrics,
    LLMExplanation,
    AnalysisListItem
)
from app.services.pos_parser import POSParser, POSParseError
from app.services.cashflow_engine import CashFlowEngine
from app.services.llm_router import LLMRouter
from app.services.cache import CacheService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cashflow", tags=["cashflow"])


@router.post("/analyze", response_model=CashFlowAnalysisResponse)
async def analyze_cashflow(
    csv_file: UploadFile = File(..., description="POS CSV file with date and amount columns"),
    rent: float = Form(..., gt=0, description="Monthly rent"),
    payroll: float = Form(..., ge=0, description="Monthly payroll"),
    other: float = Form(..., ge=0, description="Other monthly fixed costs"),
    cash_on_hand: Optional[float] = Form(None, ge=0, description="Current cash reserves"),
    business_name: Optional[str] = Form(None, description="Business name"),
    db: Session = Depends(get_db)
):
    """
    Analyze cash flow from POS CSV upload
    
    Accepts a CSV file with at minimum 'date' and 'amount' columns,
    plus fixed cost information. Returns computed metrics and LLM explanation.
    """
    try:
        # Read CSV file
        file_content = await csv_file.read()
        
        # Parse CSV into daily revenue
        daily_revenue_list, detected_business_name = POSParser.parse_csv(
            file_content, 
            business_name
        )
        
        # Use detected name if not provided
        final_business_name = business_name or detected_business_name
        
        # Build fixed costs dict
        fixed_costs = {
            "rent": rent,
            "payroll": payroll,
            "other": other,
            "cash_on_hand": cash_on_hand
        }
        
        # Compute metrics
        metrics = CashFlowEngine.compute_metrics(daily_revenue_list, fixed_costs)
        
        # Create analysis record
        analysis = Analysis(
            business_name=final_business_name,
            data_days=len(daily_revenue_list),
            risk_state=metrics["risk_state"],
            confidence=metrics["confidence"]
        )
        db.add(analysis)
        db.flush()  # Get ID
        
        # Store daily revenue
        for revenue_record in daily_revenue_list:
            daily_rev = DailyRevenue(
                analysis_id=analysis.id,
                date=revenue_record["date"],
                revenue=revenue_record["revenue"]
            )
            db.add(daily_rev)
        
        # Store fixed costs
        fixed_cost_record = FixedCost(
            analysis_id=analysis.id,
            rent=rent,
            payroll=payroll,
            other=other,
            cash_on_hand=cash_on_hand
        )
        db.add(fixed_cost_record)
        
        db.commit()
        db.refresh(analysis)
        
        logger.info(f"Created analysis {analysis.id} with {len(daily_revenue_list)} days")
        
        # Get LLM explanation (with caching)
        cache_key = LLMRouter.generate_cache_key(
            {"metrics": metrics, "fixed_costs": fixed_costs},
            "deepseek-r1"
        )
        
        cached_explanation = CacheService.get_llm_output(db, cache_key)
        
        if cached_explanation:
            explanation_dict = cached_explanation
        else:
            explanation_dict = await LLMRouter.call_deepseek_r1(metrics, fixed_costs)
            CacheService.set_llm_output(db, cache_key, "deepseek-r1", explanation_dict)
        
        # Build response
        return CashFlowAnalysisResponse(
            analysis_id=analysis.id,
            business_name=final_business_name,
            data_days=len(daily_revenue_list),
            metrics=CashFlowMetrics(**metrics),
            explanation=LLMExplanation(**explanation_dict),
            created_at=analysis.created_at.isoformat()
        )
        
    except POSParseError as e:
        logger.error(f"POS parsing error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in analyze_cashflow: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/analyses", response_model=List[AnalysisListItem])
async def list_analyses(
    limit: int = 10,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    List past analyses
    
    Returns a paginated list of previous cash flow analyses
    """
    analyses = (
        db.query(Analysis)
        .order_by(Analysis.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    
    return [
        AnalysisListItem(
            id=a.id,
            created_at=a.created_at.isoformat(),
            business_name=a.business_name,
            data_days=a.data_days,
            risk_state=a.risk_state,
            confidence=a.confidence
        )
        for a in analyses
    ]


@router.get("/analyses/{analysis_id}")
async def get_analysis(
    analysis_id: int,
    db: Session = Depends(get_db)
):
    """
    Get detailed analysis by ID
    
    Returns full analysis with metrics and revenue data
    """
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Get daily revenue
    daily_revenues = (
        db.query(DailyRevenue)
        .filter(DailyRevenue.analysis_id == analysis_id)
        .order_by(DailyRevenue.date)
        .all()
    )
    
    # Get fixed costs
    fixed_costs = analysis.fixed_costs
    
    # Rebuild metrics
    revenue_list = [{"date": dr.date, "revenue": dr.revenue} for dr in daily_revenues]
    fixed_costs_dict = {
        "rent": fixed_costs.rent,
        "payroll": fixed_costs.payroll,
        "other": fixed_costs.other,
        "cash_on_hand": fixed_costs.cash_on_hand
    }
    
    metrics = CashFlowEngine.compute_metrics(revenue_list, fixed_costs_dict)
    
    return {
        "analysis_id": analysis.id,
        "created_at": analysis.created_at.isoformat(),
        "business_name": analysis.business_name,
        "data_days": analysis.data_days,
        "metrics": metrics,
        "daily_revenues": [
            {"date": dr.date.isoformat(), "revenue": dr.revenue}
            for dr in daily_revenues
        ],
        "fixed_costs": fixed_costs_dict
    }