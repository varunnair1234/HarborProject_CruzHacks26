from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from app.db.session import get_db
from app.schemas.shopline import (
    FeaturedBusinessInput,
    FeaturedBusinessResponse,
    FeaturedBusiness,
    ShoplineSearchInput,
    ShoplineSearchResponse,
    BusinessProfile
)
from app.services.llm_router import LLMRouter
from app.services.cache import CacheService

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
