from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
import logging
import httpx
import json
import csv
import os
from typing import List, Dict, Optional

from app.db.session import get_db
from app.schemas.touristpulse import (
    TouristPulseInput,
    TouristPulseResponse,
    TouristPulseOutlook,
    DemandSignal
)
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/touristpulse", tags=["touristpulse"])

# Santa Cruz coordinates
SANTA_CRUZ_LAT = 36.9741
SANTA_CRUZ_LON = -122.0308


async def fetch_weather_data(days: int = 15) -> Dict:
    """Fetch weather data from Open-Meteo API"""
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={SANTA_CRUZ_LAT}&longitude={SANTA_CRUZ_LON}&hourly=temperature_2m,weathercode,precipitation_probability&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max&timezone=America%2FLos_Angeles&forecast_days={days}"
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            logger.info(f"Successfully fetched weather data: {len(data.get('daily', {}).get('time', []))} days")
            return data
    except httpx.TimeoutException as e:
        logger.error(f"Weather API timeout: {e}")
        raise HTTPException(status_code=500, detail="Weather API request timed out")
    except httpx.HTTPStatusError as e:
        logger.error(f"Weather API HTTP error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=500, detail=f"Weather API error: {e.response.status_code}")
    except Exception as e:
        logger.error(f"Failed to fetch weather data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch weather data: {str(e)}")


async def fetch_traffic_data() -> Dict:
    """Fetch traffic data from TomTom API"""
    try:
        # Get TomTom API key from environment
        tomtom_key = os.getenv("TOMTOM_API_KEY")
        if not tomtom_key:
            logger.warning("TomTom API key not found, using mock data")
            return {
                "flow": {"congestionLevel": 0.3},
                "incidents": []
            }
        
        # TomTom Traffic Flow API
        traffic_flow_url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?key={tomtom_key}&point={SANTA_CRUZ_LAT},{SANTA_CRUZ_LON}"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(traffic_flow_url)
            if response.status_code == 200:
                flow_data = response.json()
                congestion = None
                if flow_data.get("flowSegmentData", {}).get("currentSpeed") and flow_data.get("flowSegmentData", {}).get("freeFlowSpeed"):
                    current = flow_data["flowSegmentData"]["currentSpeed"]
                    free = flow_data["flowSegmentData"]["freeFlowSpeed"]
                    congestion = 1 - (current / free) if free > 0 else None
                
                return {
                    "flow": {"congestionLevel": congestion},
                    "incidents": []
                }
            else:
                logger.warning(f"TomTom API returned {response.status_code}")
                return {
                    "flow": {"congestionLevel": 0.3},
                    "incidents": []
                }
    except Exception as e:
        logger.error(f"Failed to fetch traffic data: {e}")
        return {
            "flow": {"congestionLevel": 0.3},
            "incidents": []
        }


def load_events() -> List[Dict]:
    """Load events from CSV file"""
    events = []
    # Get the backend directory (parent of app directory)
    # __file__ is: backend/app/routers/touristpulse.py
    # So backend_dir should be: backend/
    current_file = os.path.abspath(__file__)  # /path/to/backend/app/routers/touristpulse.py
    app_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))  # /path/to/backend
    backend_dir = app_dir  # backend directory
    
    # Try multiple possible paths for the CSV
    possible_paths = [
        os.path.join(backend_dir, "santa_cruz_events_combined.csv"),  # backend/santa_cruz_events_combined.csv (most likely on Render)
        os.path.join(os.path.dirname(current_file), "../../../santa_cruz_events_combined.csv"),  # Relative from router
        os.path.join(os.getcwd(), "santa_cruz_events_combined.csv"),  # Current working directory
        os.path.join(os.getcwd(), "backend", "santa_cruz_events_combined.csv"),  # If cwd is repo root
        "santa_cruz_events_combined.csv",  # Just filename (if in cwd)
    ]
    
    logger.info(f"Attempting to load events CSV")
    logger.info(f"Current file: {current_file}")
    logger.info(f"Backend dir: {backend_dir}")
    logger.info(f"Current working directory: {os.getcwd()}")
    
    for path in possible_paths:
        abs_path = os.path.abspath(path)
        exists = os.path.exists(path)
        logger.info(f"Trying path: {abs_path} (exists: {exists})")
        
        if exists:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get('name') and row.get('date'):
                            events.append({
                                'name': row['name'],
                                'date': row['date'],
                                'location': row.get('location', 'Santa Cruz'),
                                'type': row.get('type', 'community')
                            })
                logger.info(f"✅ Successfully loaded {len(events)} events from {abs_path}")
                return events  # Return immediately on success
            except Exception as e:
                logger.error(f"Failed to load events from {path}: {e}", exc_info=True)
                continue
    
    # If we get here, no CSV was found
    logger.warning("⚠️ No events CSV file found. Predictions will work without event data.")
    logger.warning(f"Checked paths: {[os.path.abspath(p) for p in possible_paths]}")
    return events  # Return empty list


def get_weather_condition(weathercode: int) -> str:
    """Convert WMO weather code to condition"""
    if weathercode == 0 or weathercode == 1:
        return "Clear sky"
    elif weathercode >= 2 and weathercode <= 3:
        return "Partly cloudy"
    elif weathercode >= 45 and weathercode <= 48:
        return "Fog"
    elif weathercode >= 51 and weathercode <= 67:
        return "Rain"
    elif weathercode >= 71 and weathercode <= 86:
        return "Snow"
    elif weathercode >= 95:
        return "Thunderstorm"
    return "Cloudy"


async def call_llm_for_prediction(date_str: str, weather: Dict, traffic: Dict, events: List[Dict]) -> Dict:
    """Call DeepSeek via OpenRouter for tourism prediction"""
    try:
        # Use OpenRouter API key (same as other modules)
        openrouter_key = settings.openrouter_api_key
        
        if not openrouter_key:
            logger.warning("OpenRouter API key not found, using fallback prediction")
            # Return a simple prediction based on weather and events
            level = "normal"
            factor = 1.0
            if weather.get('condition', '').lower() in ['clear sky', 'sunny']:
                level = "high"
                factor = 1.3
            if len(events) > 0:
                level = "high"
                factor = 1.5
            return {
                "level": level,
                "factor": factor,
                "reasoning": "Prediction based on weather and events (LLM unavailable)",
                "confidence": 0.6
            }
        
        # Build prompt
        events_text = "\n".join([f"- {e['name']} ({e['type']})" for e in events]) if events else "No major events scheduled"
        
        prompt = f"""You are a tourism prediction expert for Santa Cruz, California. Based on the following data, predict the tourism level for {date_str}.

WEATHER DATA:
- Condition: {weather['condition']}
- Temperature: {weather['temp_min']}°F - {weather['temp_max']}°F
- Precipitation Probability: {weather['precipitation_probability']}%

TRAFFIC DATA:
- Congestion Level: {traffic.get('flow', {}).get('congestionLevel', 0) * 100 if traffic.get('flow', {}).get('congestionLevel') else 0:.0f}%
- Traffic Incidents: {len(traffic.get('incidents', []))}

EVENTS:
{events_text}

Based on this data, predict the tourism level for Santa Cruz on {date_str}. Consider:
- Weather conditions (sunny/clear = higher tourism, rainy = lower)
- Temperature (warm = higher, cold = lower)
- Events (major events = higher tourism)
- Traffic patterns (more congestion = more people = higher tourism)
- Day of week (weekends typically higher)

Respond with ONLY a JSON object in this exact format:
{{
  "level": "low" | "normal" | "high" | "very high",
  "factor": <number between 0.5 and 2.0 representing multiplier vs normal>,
  "reasoning": "<brief 1-2 sentence explanation>",
  "confidence": <number between 0 and 1>
}}"""

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek/deepseek-chat",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a helpful assistant that predicts tourism levels. Always respond with valid JSON only, no additional text.",
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                    "temperature": 0.3,
                    "max_tokens": 200,
                }
            )
            response.raise_for_status()
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Parse JSON
            try:
                return json.loads(content)
            except:
                # Try to extract JSON from markdown
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                return json.loads(content)
    except Exception as e:
        logger.error(f"LLM prediction failed: {e}")
        # Fallback prediction
        return {
            "level": "normal",
            "factor": 1.0,
            "reasoning": "Unable to generate prediction",
            "confidence": 0.5
        }


@router.get("/outlook", response_model=TouristPulseResponse)
async def get_tourist_outlook(
    location: str = "Santa Cruz",
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Get tourist demand outlook for a location
    
    Integrates:
    - Open-Meteo weather API for weather data
    - TomTom traffic API for traffic data
    - Local events CSV for event data
    - DeepSeek LLM for demand analysis
    """
    logger.info(f"Tourist outlook requested for {location}, {days} days")
    
    try:
        # Fetch external data
        weather_data = await fetch_weather_data(days)
        traffic_data = await fetch_traffic_data()
        events = load_events()
        
        # Generate outlook for each day
        outlook = []
        start_date = date.today()
        
        for i in range(min(days, len(weather_data.get("daily", {}).get("time", [])))):
            current_date = start_date + timedelta(days=i)
            date_str = current_date.isoformat()
            
            # Get weather for this date
            daily_weather = None
            if "daily" in weather_data and "time" in weather_data["daily"]:
                try:
                    idx = weather_data["daily"]["time"].index(date_str)
                    daily_weather = {
                        "weathercode": weather_data["daily"]["weathercode"][idx],
                        "temp_max": weather_data["daily"]["temperature_2m_max"][idx],
                        "temp_min": weather_data["daily"]["temperature_2m_min"][idx],
                        "precipitation_probability": weather_data["daily"].get("precipitation_probability_max", [0])[idx] if "precipitation_probability_max" in weather_data["daily"] else 0
                    }
                except (ValueError, IndexError):
                    continue
            
            if not daily_weather:
                continue
            
            # Find events for this date
            day_events = [e for e in events if e.get('date') == date_str]
            
            # Get LLM prediction
            weather_condition = get_weather_condition(daily_weather["weathercode"])
            prediction = await call_llm_for_prediction(
                date_str,
                {
                    "condition": weather_condition,
                    "temp_max": daily_weather["temp_max"],
                    "temp_min": daily_weather["temp_min"],
                    "precipitation_probability": daily_weather["precipitation_probability"]
                },
                traffic_data,
                day_events
            )
            
            # Map prediction level to demand level (matching schema)
            level_map = {
                "low": "low",
                "normal": "moderate",
                "high": "high",
                "very high": "very_high"
            }
            demand_level = level_map.get(prediction.get("level", "normal"), "moderate")
            
            # Build demand signals
            signals = [
                DemandSignal(
                    source="weather",
                    factor=weather_condition.lower(),
                    impact="positive" if "clear" in weather_condition.lower() or "sunny" in weather_condition.lower() else "negative",
                    weight=0.4
                )
            ]
            
            if day_events:
                signals.append(
                    DemandSignal(
                        source="events",
                        factor=f"{len(day_events)} event(s)",
                        impact="positive",
                        weight=0.3
                    )
                )
            
            if traffic_data.get("flow", {}).get("congestionLevel"):
                signals.append(
                    DemandSignal(
                        source="traffic",
                        factor="congestion",
                        impact="positive",
                        weight=0.3
                    )
                )
            
            outlook.append(
                TouristPulseOutlook(
                    date=current_date,
                    demand_level=demand_level,
                    confidence=prediction.get("confidence", 0.6),
                    drivers=signals,
                    summary=prediction.get("reasoning", f"Tourism level: {demand_level}")
                )
            )
        
        return TouristPulseResponse(
            location=location,
            outlook=outlook,
            generated_at=datetime.utcnow().isoformat()
        )
        
    except HTTPException as e:
        # Re-raise HTTP exceptions (like from fetch_weather_data)
        logger.error(f"HTTPException in tourist outlook: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Failed to generate tourist outlook: {e}", exc_info=True)
        # Return error details in response for debugging
        error_msg = str(e)
        error_type = type(e).__name__
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to generate outlook: {error_type}: {error_msg}. Check backend logs for details."
        )
