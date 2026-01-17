from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
import logging
import httpx
import json
import csv
import os
from typing import List, Dict

from app.db.session import get_db
from app.schemas.touristpulse import (
    TouristPulseResponse,
    TouristPulseOutlook,
    DemandSignal,
)
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/touristpulse", tags=["touristpulse"])

# Santa Cruz coordinates
SANTA_CRUZ_LAT = 36.9741
SANTA_CRUZ_LON = -122.0308

# Open-Meteo forecast_days max
OPEN_METEO_MAX_DAYS = 16


def clamp_days(days: int) -> int:
    """Clamp days to Open-Meteo allowed range."""
    if days is None:
        return 7
    return max(1, min(int(days), OPEN_METEO_MAX_DAYS))


async def fetch_weather_data(days: int = 16) -> Dict:
    """Fetch weather data from Open-Meteo API (max 16 days)."""
    days = clamp_days(days)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={SANTA_CRUZ_LAT}"
        f"&longitude={SANTA_CRUZ_LON}"
        "&hourly=temperature_2m,weathercode,precipitation_probability"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max"
        "&timezone=America%2FLos_Angeles"
        f"&forecast_days={days}"
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            logger.info(
                "Successfully fetched weather data: %s days",
                len(data.get("daily", {}).get("time", [])),
            )
            return data
    except httpx.TimeoutException as e:
        logger.error("Weather API timeout: %s", e)
        raise HTTPException(status_code=502, detail="Weather API request timed out")
    except httpx.HTTPStatusError as e:
        logger.error("Weather API HTTP error: %s - %s", e.response.status_code, e.response.text)
        raise HTTPException(status_code=502, detail=f"Weather API error: {e.response.status_code}")
    except Exception as e:
        logger.error("Failed to fetch weather data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch weather data: {str(e)}")


async def fetch_traffic_data() -> Dict:
    """Fetch traffic data from TomTom API (optional). Falls back to mock."""
    try:
        tomtom_key = os.getenv("TOMTOM_API_KEY")
        if not tomtom_key:
            logger.warning("TomTom API key not found, using mock data")
            return {"flow": {"congestionLevel": 0.3}, "incidents": []}

        traffic_flow_url = (
            "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
            f"?key={tomtom_key}&point={SANTA_CRUZ_LAT},{SANTA_CRUZ_LON}"
        )

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(traffic_flow_url)

        if response.status_code != 200:
            logger.warning("TomTom API returned %s, using mock congestion", response.status_code)
            return {"flow": {"congestionLevel": 0.3}, "incidents": []}

        flow_data = response.json()
        seg = flow_data.get("flowSegmentData", {})
        current = seg.get("currentSpeed")
        free = seg.get("freeFlowSpeed")

        congestion = None
        if current is not None and free:
            congestion = 1 - (current / free) if free > 0 else None

        return {"flow": {"congestionLevel": congestion}, "incidents": []}

    except Exception as e:
        logger.error("Failed to fetch traffic data: %s", e, exc_info=True)
        return {"flow": {"congestionLevel": 0.3}, "incidents": []}


def load_events() -> List[Dict]:
    """Load events from CSV file if present; otherwise return empty."""
    events: List[Dict] = []

    current_file = os.path.abspath(__file__)
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))  # backend/

    possible_paths = [
        os.path.join(backend_dir, "santa_cruz_events_combined.csv"),
        os.path.join(os.getcwd(), "santa_cruz_events_combined.csv"),
        os.path.join(os.getcwd(), "backend", "santa_cruz_events_combined.csv"),
        "santa_cruz_events_combined.csv",
    ]

    logger.info("Attempting to load events CSV")
    logger.info("Current file: %s", current_file)
    logger.info("Backend dir: %s", backend_dir)
    logger.info("CWD: %s", os.getcwd())

    for path in possible_paths:
        abs_path = os.path.abspath(path)
        exists = os.path.exists(path)
        logger.info("Trying path: %s (exists: %s)", abs_path, exists)

        if not exists:
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("name") and row.get("date"):
                        events.append(
                            {
                                "name": row["name"],
                                "date": row["date"],
                                "location": row.get("location", "Santa Cruz"),
                                "type": row.get("type", "community"),
                            }
                        )
            logger.info("✅ Loaded %s events from %s", len(events), abs_path)
            return events
        except Exception as e:
            logger.error("Failed to load events from %s: %s", abs_path, e, exc_info=True)

    logger.warning("⚠️ No events CSV file found. Predictions will work without event data.")
    return events


def get_weather_condition(weathercode: int) -> str:
    """Convert WMO weather code to a coarse condition string."""
    if weathercode in (0, 1):
        return "Clear sky"
    if 2 <= weathercode <= 3:
        return "Partly cloudy"
    if 45 <= weathercode <= 48:
        return "Fog"
    if 51 <= weathercode <= 67:
        return "Rain"
    if 71 <= weathercode <= 86:
        return "Snow"
    if weathercode >= 95:
        return "Thunderstorm"
    return "Cloudy"


async def call_llm_for_prediction(date_str: str, weather: Dict, traffic: Dict, events: List[Dict]) -> Dict:
    """Call DeepSeek via OpenRouter for tourism prediction; fallback if no key."""
    try:
        openrouter_key = settings.openrouter_api_key

        if not openrouter_key:
            logger.warning("OpenRouter API key not found, using fallback prediction")
            level = "normal"
            factor = 1.0
            cond = (weather.get("condition") or "").lower()
            if "clear" in cond or "sunny" in cond:
                level, factor = "high", 1.3
            if events:
                level, factor = "high", max(factor, 1.5)

            return {
                "level": level,
                "factor": factor,
                "reasoning": "Prediction based on weather and events (LLM unavailable)",
                "confidence": 0.6,
            }

        events_text = "\n".join([f"- {e['name']} ({e.get('type','event')})" for e in events]) if events else "No major events scheduled"

        prompt = f"""You are a tourism prediction expert for Santa Cruz, California. Predict the tourism level for {date_str}.

WEATHER:
- Condition: {weather['condition']}
- Temperature: {weather['temp_min']}°F - {weather['temp_max']}°F
- Precipitation Probability: {weather['precipitation_probability']}%

TRAFFIC:
- Congestion Level: {traffic.get('flow', {}).get('congestionLevel', 0) * 100 if traffic.get('flow', {}).get('congestionLevel') is not None else 0:.0f}%
- Traffic Incidents: {len(traffic.get('incidents', []))}

EVENTS:
{events_text}

Return ONLY valid JSON in exactly this schema:
{{
  "level": "low" | "normal" | "high" | "very high",
  "factor": <number 0.5 to 2.0>,
  "reasoning": "<brief 1-2 sentence explanation>",
  "confidence": <number 0 to 1>
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
                            "content": "Return ONLY valid JSON. No markdown. No extra text.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 220,
                },
            )
            response.raise_for_status()

        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()

        # Robust JSON parse (handle occasional code fences)
        try:
            return json.loads(content)
        except Exception:
            if "```" in content:
                content = content.split("```", 1)[1]
                content = content.split("```", 1)[0].strip()
            return json.loads(content)

    except Exception as e:
        logger.error("LLM prediction failed: %s", e, exc_info=True)
        return {"level": "normal", "factor": 1.0, "reasoning": "Unable to generate prediction", "confidence": 0.5}


@router.get("/outlook", response_model=TouristPulseResponse)
async def get_tourist_outlook(
    location: str = "Santa Cruz",
    days: int = Query(16, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """
    Get tourist demand outlook for a location.

    Notes:
    - Open-Meteo supports a maximum of 16 forecast days; requests above that will be clamped.
    """
    requested_days = days
    days = clamp_days(days)

    logger.info("Tourist outlook requested for %s, requested=%s days (clamped=%s)", location, requested_days, days)

    try:
        weather_data = await fetch_weather_data(days)
        traffic_data = await fetch_traffic_data()
        events = load_events()

        daily = weather_data.get("daily") or {}
        daily_times: List[str] = daily.get("time") or []

        if not daily_times:
            raise HTTPException(status_code=502, detail="Weather API returned no daily forecast data")

        start_date = date.today()
        outlook: List[TouristPulseOutlook] = []

        # iterate by index (safer/faster than .index lookups)
        for i in range(min(days, len(daily_times))):
            current_date = start_date + timedelta(days=i)
            date_str = current_date.isoformat()

            try:
                weathercode = daily["weathercode"][i]
                temp_max = daily["temperature_2m_max"][i]
                temp_min = daily["temperature_2m_min"][i]
                precip_prob = (daily.get("precipitation_probability_max") or [0] * len(daily_times))[i]
            except Exception:
                continue

            day_events = [e for e in events if e.get("date") == date_str]

            weather_condition = get_weather_condition(int(weathercode))
            prediction = await call_llm_for_prediction(
                date_str,
                {
                    "condition": weather_condition,
                    "temp_max": temp_max,
                    "temp_min": temp_min,
                    "precipitation_probability": precip_prob,
                },
                traffic_data,
                day_events,
            )

            level_map = {"low": "low", "normal": "moderate", "high": "high", "very high": "very_high"}
            demand_level = level_map.get(prediction.get("level", "normal"), "moderate")

            signals = [
                DemandSignal(
                    source="weather",
                    factor=weather_condition.lower(),
                    impact="positive" if ("clear" in weather_condition.lower() or "sunny" in weather_condition.lower()) else "negative",
                    weight=0.4,
                )
            ]

            if day_events:
                signals.append(
                    DemandSignal(
                        source="events",
                        factor=f"{len(day_events)} event(s)",
                        impact="positive",
                        weight=0.3,
                    )
                )

            if traffic_data.get("flow", {}).get("congestionLevel") is not None:
                signals.append(
                    DemandSignal(
                        source="traffic",
                        factor="congestion",
                        impact="positive",
                        weight=0.3,
                    )
                )

            outlook.append(
                TouristPulseOutlook(
                    date=current_date,
                    demand_level=demand_level,
                    confidence=float(prediction.get("confidence", 0.6)),
                    drivers=signals,
                    summary=prediction.get("reasoning", f"Tourism level: {demand_level}"),
                )
            )

        return TouristPulseResponse(
            location=location,
            outlook=outlook,
            generated_at=datetime.utcnow().isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to generate tourist outlook: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate outlook: {type(e).__name__}: {str(e)}")
