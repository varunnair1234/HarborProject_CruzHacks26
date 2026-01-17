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


class ShoplineEventSearchInput(BaseModel):
    """Input for event recommendation"""
    categories: List[str] = Field(..., description="Selected event categories")
    query: Optional[str] = Field(None, description="Optional free-text query")
    limit: int = Field(10, description="Max number of events to return")


class ShoplineEvent(BaseModel):
    """Event returned by Shopline"""
    id: str
    title: str
    description: Optional[str]
    start_time: Optional[str]
    location: Optional[str]
    categories: List[str]
    url: Optional[str]
    source: Optional[str]


class ShoplineEventSearchResponse(BaseModel):
    """Event recommendation response"""
    categories: List[str]
    query: Optional[str]
    results: List[ShoplineEvent]
    total: int
    generated_at: str
