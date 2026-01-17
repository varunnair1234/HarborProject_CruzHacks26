from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date


class TouristPulseInput(BaseModel):
    """Input for tourist demand outlook"""
    location: str = Field(..., description="Location (city, zip, or coordinates)")
    date_range_start: Optional[date] = Field(None, description="Start of forecast period")
    date_range_end: Optional[date] = Field(None, description="End of forecast period")


class DemandSignal(BaseModel):
    """Individual demand signal"""
    source: str  # weather, surf, events
    factor: str  # specific factor (e.g., "temperature", "swell_height", "concert")
    impact: str  # positive, negative, neutral
    weight: float  # 0.0 to 1.0


class TouristPulseOutlook(BaseModel):
    """Tourist demand outlook"""
    date: date
    demand_level: str  # low, moderate, high, very_high
    confidence: float  # 0.0 to 1.0
    drivers: List[DemandSignal]
    summary: str  # LLM-generated summary


class TouristPulseResponse(BaseModel):
    """Complete tourist pulse analysis"""
    location: str
    outlook: List[TouristPulseOutlook]
    generated_at: str
