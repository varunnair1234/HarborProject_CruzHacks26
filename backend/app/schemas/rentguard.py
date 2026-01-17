from pydantic import BaseModel, Field
from typing import Optional
from datetime import date


class RentImpactInput(BaseModel):
    """Input for rent impact simulation"""
    analysis_id: int = Field(..., description="ID of the base analysis")
    increase_pct: Optional[float] = Field(None, description="Percentage increase (e.g., 15.0 for 15%)")
    new_rent: Optional[float] = Field(None, gt=0, description="New absolute rent amount")
    effective_date: Optional[date] = Field(None, description="When the increase takes effect")


class RentImpactMetrics(BaseModel):
    """Metrics showing rent impact (business + market baseline)"""
    # Core rent change
    current_rent: float
    new_rent: float
    delta_monthly: float
    delta_pct: float

    # Fixed-cost burden + risk
    new_fixed_cost_burden: Optional[float] = Field(
        None, description="New fixed cost burden; None if revenue insufficient"
    )
    current_risk_state: str
    new_risk_state: str

    # Runway effects
    runway_impact_days: Optional[float]
    runway_transition: Optional[str] = Field(
        None, description="finite_to_infinite | infinite_to_finite"
    )
    runway_is_infinite: Optional[bool] = Field(
        None, description="True if new cashflow is positive"
    )

    # Market baseline comparison (RentGuard model)
    market_expected_land_price: Optional[float]
    market_delta_monthly: Optional[float]
    market_delta_pct: Optional[float]
    market_z_score: Optional[float]

    # Diagnostics
    revenue_insufficient: Optional[bool]


class RentImpactExplanation(BaseModel):
    """LLM or deterministic explanation of rent impact"""
    summary: str
    key_drivers: list[str]
    recommended_actions: list[str]


class RentImpactResponse(BaseModel):
    """Complete rent impact analysis"""
    scenario_id: int
    analysis_id: int
    metrics: RentImpactMetrics
    explanation: RentImpactExplanation
    created_at: str
