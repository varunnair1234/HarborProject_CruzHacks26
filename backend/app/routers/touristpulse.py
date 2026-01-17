from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
import logging

from app.db.session import get_db
from app.schemas.touristpulse import (
    TouristPulseInput,
    TouristPulseResponse,
    TouristPulseOutlook,
    DemandSignal
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/touristpulse", tags=["touristpulse"])


@router.get("/outlook", response_model=TouristPulseResponse)
async def get_tourist_outlook(
    location: str,
    days: int = 7,
    db: Session = Depends(get_db)
):
    """
    Get tourist demand outlook for a location
    
    Currently returns placeholder data. Future implementation will integrate:
    - NOAA weather API for weather data
    - Surf forecasts for coastal locations
    - Events API for local happenings
    - DeepSeek V3.1 Terminus for demand analysis
    """
    logger.info(f"Tourist outlook requested for {location}, {days} days")
    
    # Placeholder implementation
    # TODO: Integrate real weather, surf, and events APIs
    # TODO: Call DeepSeek V3.1 Terminus for demand analysis
    
    outlook = []
    start_date = date.today()
    
    for i in range(days):
        current_date = start_date + timedelta(days=i)
        
        # Mock demand signals
        signals = [
            DemandSignal(
                source="weather",
                factor="temperature",
                impact="positive",
                weight=0.7
            ),
            DemandSignal(
                source="events",
                factor="local_festival",
                impact="positive",
                weight=0.3
            )
        ]
        
        outlook.append(
            TouristPulseOutlook(
                date=current_date,
                demand_level="moderate",
                confidence=0.6,
                drivers=signals,
                summary=f"Moderate tourist activity expected in {location}"
            )
        )
    
    return TouristPulseResponse(
        location=location,
        outlook=outlook,
        generated_at=datetime.utcnow().isoformat()
    )
