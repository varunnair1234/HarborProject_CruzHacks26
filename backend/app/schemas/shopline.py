from pydantic import BaseModel, Field
from typing import List, Optional, Literal


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


# ===== Shopline Analyst Schemas =====

class BusinessMetricsInput(BaseModel):
    """Business performance metrics for analysis"""
    avg_daily_revenue: Optional[float] = Field(None, description="Average daily revenue")
    trend_7d: Optional[float] = Field(None, description="7-day revenue trend as decimal")
    trend_14d: Optional[float] = Field(None, description="14-day revenue trend as decimal")
    trend_30d: Optional[float] = Field(None, description="30-day revenue trend as decimal")
    volatility: Optional[float] = Field(None, description="Revenue volatility (coefficient of variation)")
    fixed_cost_burden: Optional[float] = Field(None, description="Fixed costs as fraction of revenue")
    runway_days: Optional[float] = Field(None, description="Cash runway in days")
    risk_state: Optional[str] = Field(None, description="Current risk state: healthy, caution, critical")


class LocalSignalsInput(BaseModel):
    """Local demand signals for analysis"""
    weather_forecast: Optional[List[dict]] = Field(None, description="7-day weather forecast")
    upcoming_events: Optional[List[dict]] = Field(None, description="Upcoming local events")
    day_of_week_pattern: Optional[dict] = Field(None, description="Day-of-week revenue patterns")
    seasonality_factor: Optional[float] = Field(None, description="Current seasonality multiplier")


class ShoplineAnalysisInput(BaseModel):
    """Input for Shopline business analysis"""
    business_name: str = Field(..., description="Business name")
    business_type: str = Field(..., description="Type of business (cafe, retail, restaurant, etc.)")
    metrics: Optional[BusinessMetricsInput] = Field(None, description="Business performance metrics")
    local_signals: Optional[LocalSignalsInput] = Field(None, description="Local demand signals")
    analysis_id: Optional[int] = Field(None, description="Optional linked CashFlow analysis ID")


class DiagnosisOutput(BaseModel):
    """Business health diagnosis"""
    state: Literal["healthy", "caution", "risk"]
    why: List[str] = Field(..., min_length=3, max_length=3)


class OutlookOutput(BaseModel):
    """7-day demand outlook"""
    demand_level: Literal["low", "moderate", "high"]
    drivers: List[str] = Field(..., min_length=1, max_length=4)
    suppressors: List[str] = Field(default_factory=list, max_length=3)


class ActionItem(BaseModel):
    """Prioritized action recommendation"""
    action: str
    reason: str
    expected_impact: Literal["low", "medium", "high"]
    effort: Literal["low", "medium", "high"]


class ShoplineAnalysisResponse(BaseModel):
    """Full Shopline analysis response"""
    summary: str
    diagnosis: DiagnosisOutput
    next_7_days_outlook: OutlookOutput
    prioritized_actions: List[ActionItem] = Field(..., min_length=3, max_length=5)
    watchlist: List[str] = Field(..., min_length=3, max_length=6)
    confidence: float = Field(..., ge=0.0, le=1.0)
    limitations: str
    generated_at: str
