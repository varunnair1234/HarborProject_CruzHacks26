from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from app.db.session import get_db
from app.db.models import Analysis, DailyRevenue
from app.schemas.shopline import (
    FeaturedBusinessInput,
    FeaturedBusinessResponse,
    FeaturedBusiness,
    ShoplineSearchInput,
    ShoplineSearchResponse,
    BusinessProfile,
    ShoplineAnalysisInput,
    ShoplineAnalysisResponse,
    DiagnosisOutput,
    OutlookOutput,
    ActionItem
)
from app.services.llm_router import LLMRouter
from app.services.cache import CacheService
from app.services.cashflow_engine import CashFlowEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shopline", tags=["shopline"])


@router.post("/search", response_model=ShoplineSearchResponse)
async def search_businesses(
    search_input: ShoplineSearchInput,
    db: Session = Depends(get_db)
):
    """
    Search for local businesses
    
    Currently returns placeholder data. Future implementation will integrate:
    - OpenStreetMap API for business discovery
    - Yelp/Google Places for business details
    - Local business databases
    """
    logger.info(f"Business search: {search_input.query}")
    
    # Placeholder results
    # TODO: Integrate OpenStreetMap API and business databases
    
    results = [
        BusinessProfile(
            name="Sample Coffee Shop",
            category="cafe",
            location="Downtown",
            description="Locally roasted coffee and pastries"
        ),
        BusinessProfile(
            name="Harbor Books",
            category="bookstore",
            location="Waterfront",
            description="Independent bookstore since 1985"
        )
    ]
    
    return ShoplineSearchResponse(
        query=search_input.query,
        results=results,
        total=len(results)
    )


@router.post("/featured", response_model=FeaturedBusinessResponse)
async def generate_featured_businesses(
    input_data: FeaturedBusinessInput,
    db: Session = Depends(get_db)
):
    """
    Generate featured business rankings with AI-powered blurbs
    
    Uses Gemini 2 Flash to create compelling descriptions and rankings
    for local businesses based on provided criteria.
    """
    logger.info(f"Generating featured businesses for {len(input_data.businesses)} businesses")
    
    featured = []
    
    for business in input_data.businesses:
        # Get LLM-generated blurb (with caching)
        cache_key = LLMRouter.generate_cache_key(
            {
                "name": business.name,
                "category": business.category,
                "location": business.location,
                "description": business.description
            },
            "gemini-featured"
        )
        
        cached_result = CacheService.get_llm_output(db, cache_key)
        
        if cached_result:
            gemini_output = cached_result
        else:
            try:
                gemini_output = await LLMRouter.call_gemini(
                    business.dict(),
                    input_data.ranking_factors or {}
                )
                CacheService.set_llm_output(db, cache_key, "gemini-2-flash", gemini_output)
            except Exception as e:
                logger.error(f"Gemini call failed for {business.name}: {e}")
                # Fallback
                gemini_output = {
                    "blurb": f"Featured local business in {business.category}",
                    "highlights": ["Local favorite", "Quality service"],
                    "score": 75.0
                }
        
        featured.append(
            FeaturedBusiness(
                name=business.name,
                category=business.category,
                location=business.location,
                score=gemini_output.get("score", 75.0),
                blurb=gemini_output.get("blurb", ""),
                highlights=gemini_output.get("highlights", [])
            )
        )
    
    # Sort by score descending
    featured.sort(key=lambda x: x.score, reverse=True)

    return FeaturedBusinessResponse(
        featured=featured,
        generated_at=datetime.utcnow().isoformat()
    )


@router.post("/analyze", response_model=ShoplineAnalysisResponse)
async def analyze_business(
    input_data: ShoplineAnalysisInput,
    db: Session = Depends(get_db)
):
    """
    Generate comprehensive business analysis using Shopline AI analyst

    Combines business performance metrics with local demand signals
    to produce actionable insights and recommendations.
    """
    logger.info(f"Shopline analysis requested for: {input_data.business_name}")

    try:
        # Build input data for LLM
        llm_input = {
            "business_name": input_data.business_name,
            "business_type": input_data.business_type,
            "location": "Santa Cruz, CA"
        }

        # Add metrics if provided
        if input_data.metrics:
            llm_input["metrics"] = input_data.metrics.model_dump(exclude_none=True)

        # If analysis_id provided, fetch metrics from CashFlow analysis
        if input_data.analysis_id:
            analysis = db.query(Analysis).filter(Analysis.id == input_data.analysis_id).first()
            if analysis:
                daily_revenues = (
                    db.query(DailyRevenue)
                    .filter(DailyRevenue.analysis_id == input_data.analysis_id)
                    .all()
                )

                if daily_revenues and analysis.fixed_costs:
                    revenue_list = [{"date": dr.date, "revenue": dr.revenue} for dr in daily_revenues]
                    fixed_costs_dict = {
                        "rent": float(analysis.fixed_costs.rent or 0),
                        "payroll": float(analysis.fixed_costs.payroll or 0),
                        "other": float(analysis.fixed_costs.other or 0),
                        "cash_on_hand": float(analysis.fixed_costs.cash_on_hand or 0)
                    }

                    metrics = CashFlowEngine.compute_metrics(revenue_list, fixed_costs_dict)
                    llm_input["metrics"] = {
                        "avg_daily_revenue": metrics.get("avg_daily_revenue"),
                        "trend_7d": metrics.get("trend_7d"),
                        "trend_14d": metrics.get("trend_14d"),
                        "trend_30d": metrics.get("trend_30d"),
                        "volatility": metrics.get("volatility"),
                        "fixed_cost_burden": metrics.get("fixed_cost_burden"),
                        "runway_days": metrics.get("runway_days"),
                        "risk_state": metrics.get("risk_state")
                    }
                    llm_input["data_days"] = len(daily_revenues)

        # Add local signals if provided
        if input_data.local_signals:
            llm_input["local_signals"] = input_data.local_signals.model_dump(exclude_none=True)

        # Check cache
        cache_key = LLMRouter.generate_cache_key(llm_input, "shopline-analyst")
        cached_result = CacheService.get_llm_output(db, cache_key)

        if cached_result:
            analysis_result = cached_result
            logger.info("Using cached Shopline analysis")
        else:
            # Call LLM
            analysis_result = await LLMRouter.call_shopline_analyst(llm_input)
            CacheService.set_llm_output(db, cache_key, "gemini-shopline", analysis_result)
            logger.info("Generated new Shopline analysis")

        # Build response with validation
        return ShoplineAnalysisResponse(
            summary=analysis_result.get("summary", "Analysis complete."),
            diagnosis=DiagnosisOutput(
                state=analysis_result.get("diagnosis", {}).get("state", "caution"),
                why=analysis_result.get("diagnosis", {}).get("why", [
                    "Unable to fully assess business health.",
                    "Some metrics may be missing.",
                    "Review data inputs for completeness."
                ])[:3]
            ),
            next_7_days_outlook=OutlookOutput(
                demand_level=analysis_result.get("next_7_days_outlook", {}).get("demand_level", "moderate"),
                drivers=analysis_result.get("next_7_days_outlook", {}).get("drivers", ["Insufficient data for drivers."]),
                suppressors=analysis_result.get("next_7_days_outlook", {}).get("suppressors", [])
            ),
            prioritized_actions=[
                ActionItem(**action) for action in analysis_result.get("prioritized_actions", [
                    {"action": "Review business data", "reason": "Ensure complete metrics", "expected_impact": "medium", "effort": "low"}
                ])[:5]
            ],
            watchlist=analysis_result.get("watchlist", ["Daily revenue", "Customer traffic", "Weather"])[:6],
            confidence=min(max(analysis_result.get("confidence", 0.5), 0.0), 1.0),
            limitations=analysis_result.get("limitations", "Analysis based on available data."),
            generated_at=datetime.utcnow().isoformat()
        )

    except Exception as e:
        logger.error(f"Shopline analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
