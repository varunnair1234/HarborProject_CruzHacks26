from pydantic import BaseModel, Field
from typing import List, Optional


class BusinessProfile(BaseModel):
    """Business profile for Shopline"""
    name: str
    category: str
    location: str
    description: Optional[str] = None


class FeaturedBusinessInput(BaseModel):
    """Input for featured business ranking"""
    businesses: List[BusinessProfile]
    ranking_factors: Optional[dict] = Field(
        None,
        description="Custom ranking factors (e.g., {'local': 0.3, 'sustainable': 0.2})"
    )


class FeaturedBusiness(BaseModel):
    """Featured business with score and blurb"""
    name: str
    category: str
    location: str
    score: float  # 0.0 to 100.0
    blurb: str  # Gemini-generated description
    highlights: List[str]  # Key features


class ShoplineSearchInput(BaseModel):
    """Input for business search"""
    query: str = Field(..., description="Search query")
    category: Optional[str] = Field(None, description="Filter by category")
    location: Optional[str] = Field(None, description="Filter by location")


class ShoplineSearchResponse(BaseModel):
    """Search results"""
    query: str
    results: List[BusinessProfile]
    total: int


class FeaturedBusinessResponse(BaseModel):
    """Featured businesses response"""
    featured: List[FeaturedBusiness]
    generated_at: str
