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
    """Metrics showing rent impact"""
    current_rent: float
    new_rent: float
    delta_monthly: float
    delta_pct: float
    new_fixed_cost_burden: float
    current_risk_state: str
    new_risk_state: str
    runway_impact_days: Optional[float]


class RentImpactExplanation(BaseModel):
    """LLM explanation of rent impact"""
    summary: str
    concerns: list[str]
    recommendations: list[str]


class RentImpactResponse(BaseModel):
    """Complete rent impact analysis"""
    scenario_id: int
    analysis_id: int
    metrics: RentImpactMetrics
    explanation: RentImpactExplanation
    created_at: str
