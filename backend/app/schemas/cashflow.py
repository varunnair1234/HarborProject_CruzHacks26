from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date


class FixedCostsInput(BaseModel):
    """Fixed costs input for analysis"""
    rent: float = Field(..., gt=0, description="Monthly rent")
    payroll: float = Field(..., ge=0, description="Monthly payroll")
    other: float = Field(..., ge=0, description="Other monthly fixed costs")
    cash_on_hand: Optional[float] = Field(None, ge=0, description="Current cash reserves")


class CashFlowMetrics(BaseModel):
    """Computed cash flow metrics"""
    avg_daily_revenue: float
    trend_7d: float  # percentage change
    trend_14d: float
    trend_30d: float
    volatility: float  # coefficient of variation
    fixed_cost_burden: float  # monthly fixed costs / avg monthly revenue
    runway_days: Optional[float]  # days until cash runs out (if available)
    risk_horizon: int  # days to monitor
    risk_state: str  # healthy, caution, critical
    confidence: float  # 0.0 to 1.0


class LLMExplanation(BaseModel):
    """LLM-generated explanation from DeepSeek R1"""
    bullets: List[str] = Field(..., description="Key insights as bullet points")
    actions: List[str] = Field(..., description="Recommended actions")
    confidence_note: str = Field(..., description="Explanation of confidence level")


class CashFlowAnalysisResponse(BaseModel):
    """Complete analysis response"""
    analysis_id: int
    business_name: Optional[str]
    data_days: int
    metrics: CashFlowMetrics
    explanation: LLMExplanation
    created_at: str


class AnalysisListItem(BaseModel):
    """Summary of an analysis for listing"""
    id: int
    created_at: str
    business_name: Optional[str]
    data_days: int
    risk_state: str
    confidence: float
