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

# Santa Cruz coordinates (default)
SANTA_CRUZ_LAT = 36.9741
SANTA_CRUZ_LON = -122.0308

# Open-Meteo forecast_days varies by deployment; your logs show "0 to 16" but rejects 16.
# Clamp to 15 to avoid off-by-one/provider variance.
OPEN_METEO_SAFE_MAX_DAYS = 15


def _clamp_int(value: int, min_v: int, max_v: int) -> int:
    try:
        v = int(value)
    except Exception:
        v = min_v
    return max(min_v, min(v, max_v))


async def fetch_weather_data(requested_days: int = 30) -> Dict:
    """Fetch weather data from Open-Meteo API.

    We clamp forecast_days to a safe max, then degrade gracefully beyond that window.
    """
    forecast_days = _clamp_int(requested_days, 1, OPEN_METEO_SAFE_MAX_DAYS)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={SANTA_CRUZ_LAT}"
        f"&longitude={SANTA_CRUZ_LON}"
        "&hourly=temperature_2m,weathercode,precipitation_probability"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max"
        "&timezone=America%2FLos_Angeles"
        f"&forecast_days={forecast_days}"
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            n_days = len(data.get("daily", {}).get("time", []))
            logger.info(
                f"Successfully fetched weather data: {n_days} days "
                f"(requested={requested_days}, fetched={forecast_days})"
            )
            return data
    except httpx.TimeoutException as e:
        logger.error(f"Weather API timeout: {e}")
        raise HTTPException(status_code=504, detail="Weather API request timed out")
    except httpx.HTTPStatusError as e:
        logger.error(f"Weather API HTTP error: {e.response.status_code} - {e.response.text}")
        # Upstream failure -> 502 is more accurate than 500
        raise HTTPException(status_code=502, detail=f"Weather API error: {e.response.status_code}")
    except Exception as e:
        logger.error(f"Failed to fetch weather data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch weather data: {str(e)}")


async def fetch_traffic_data() -> Dict:
    """Fetch traffic data from TomTom API (optional). Falls back to mock data."""
    try:
        tomtom_key = os.getenv("TOMTOM_API_KEY")
        if not tomtom_key:
            logger.warning("TomTom API key not found, using mock traffic data")
            return {"flow": {"congestionLevel": 0.3}, "incidents": []}

        traffic_flow_url = (
            "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
            f"?key={tomtom_key}&point={SANTA_CRUZ_LAT},{SANTA_CRUZ_LON}"
        )

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(traffic_flow_url)

        if resp.status_code != 200:
            logger.warning(f"TomTom API returned {resp.status_code}, using mock traffic data")
            return {"flow": {"congestionLevel": 0.3}, "incidents": []}

        flow_data = resp.json()
        fsd = flow_data.get("flowSegmentData", {})
        current = fsd.get("currentSpeed")
        free = fsd.get("freeFlowSpeed")

        congestion = None
        if isinstance(current, (int, float)) and isinstance(free, (int, float)) and free > 0:
            congestion = 1 - (current / free)

        return {"flow": {"congestionLevel": congestion}, "incidents": []}

    except Exception as e:
        logger.error(f"Failed to fetch traffic data: {e}", exc_info=True)
        return {"flow": {"congestionLevel": 0.3}, "incidents": []}


def load_events() -> List[Dict]:
    """Load events from CSV file (optional). Returns empty list if unavailable."""
    events: List[Dict] = []

    current_file = os.path.abspath(__file__)  # backend/app/routers/touristpulse.py
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))  # backend/

    possible_paths = [
        os.path.join(backend_dir, "santa_cruz_events_combined.csv"),
        os.path.abspath(os.path.join(os.path.dirname(current_file), "../../../santa_cruz_events_combined.csv")),
        os.path.join(os.getcwd(), "santa_cruz_events_combined.csv"),
        os.path.join(os.getcwd(), "backend", "santa_cruz_events_combined.csv"),
        "santa_cruz_events_combined.csv",
    ]

    logger.info("Attempting to load events CSV")
    logger.info(f"Current file: {current_file}")
    logger.info(f"Backend dir: {backend_dir}")
    logger.info(f"Working directory: {os.getcwd()}")

    for path in possible_paths:
        abs_path = os.path.abspath(path)
        exists = os.path.exists(path)
        logger.info(f"Trying path: {abs_path} (exists: {exists})")

        if not exists:
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get("name")
                    d = row.get("date")
                    if name and d:
                        events.append(
                            {
                                "name": name,
                                "date": d,
                                "location": row.get("location", "Santa Cruz"),
                                "type": row.get("type", "community"),
                            }
                        )
            logger.info(f"✅ Successfully loaded {len(events)} events from {abs_path}")
            return events
        except Exception as e:
            logger.error(f"Failed to load events from {abs_path}: {e}", exc_info=True)

    logger.warning("⚠️ No events CSV file found. Predictions will work without event data.")
    logger.warning(f"Checked paths: {[os.path.abspath(p) for p in possible_paths]}")
    return events


def get_weather_condition(weathercode: int) -> str:
    """Convert WMO weather code to condition."""
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
    """Call DeepSeek via OpenRouter for tourism prediction.
    If unavailable, fall back to a simple heuristic.
    """
    try:
        openrouter_key = settings.openrouter_api_key

        # Fallback: deterministic, simple, and safe
        if not openrouter_key:
            logger.warning("OpenRouter API key not found, using fallback prediction")
            level = "normal"
            factor = 1.0

            cond = (weather.get("condition") or "").lower()
            if "clear" in cond or "sunny" in cond:
                level = "high"
                factor = 1.3
            if events:
                level = "high"
                factor = max(factor, 1.5)

            return {
                "level": level,
                "factor": factor,
                "reasoning": "Prediction based on weather and events (LLM unavailable).",
                "confidence": 0.6,
            }

        events_text = "\n".join([f"- {e['name']} ({e.get('type', 'event')})" for e in events]) if events else "No major events scheduled"
        congestion = traffic.get("flow", {}).get("congestionLevel")
        congestion_pct = (congestion * 100) if isinstance(congestion, (int, float)) else 0.0

        # NOTE: no system prompt (per your R1-style guidelines); keep it all in user prompt.
        prompt = f"""
You are a tourism prediction engine for Santa Cruz, California. Use ONLY the provided data. Do not invent facts.

DATE: {date_str}

WEATHER:
- Condition: {weather.get('condition')}
- Temperature range: {weather.get('temp_min')}°F to {weather.get('temp_max')}°F
- Precipitation probability: {weather.get('precipitation_probability')}%

TRAFFIC:
- Congestion level: {congestion_pct:.0f}%
- Incidents count: {len(traffic.get('incidents', []))}

EVENTS:
{events_text}

Task:
Predict tourism level for Santa Cruz on the given date. Consider:
- Clear/mild weather increases tourism; rainy/windy reduces casual tourism.
- Events increase tourism.
- Higher congestion can indicate more visitors.
- Weekends are typically higher.

Output requirements:
Respond with ONLY valid JSON (no markdown, no extra text) in this exact format:
{{
  "level": "low" | "normal" | "high" | "very high",
  "factor": <number between 0.5 and 2.0>,
  "reasoning": "<brief 1-2 sentence explanation grounded in the provided data>",
  "confidence": <number between 0 and 1>
}}
""".strip()

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                },
                json={
                    # Keep your current model unless you’ve switched the slug in OpenRouter
                    "model": "deepseek/deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "top_p": 0.95,
                    "max_tokens": 220,
                },
            )
            resp.raise_for_status()

        result = resp.json()
        content = result["choices"][0]["message"]["content"]

        # Parse JSON (handle accidental fenced output)
        try:
            return json.loads(content)
        except Exception:
            if "```json" in content:
                content = content.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in content:
                content = content.split("```", 1)[1].split("```", 1)[0].strip()
            return json.loads(content)

    except Exception as e:
        logger.error(f"LLM prediction failed: {e}", exc_info=True)
        return {
            "level": "normal",
            "factor": 1.0,
            "reasoning": "Unable to generate prediction; using baseline demand.",
            "confidence": 0.5,
        }


@router.get("/outlook", response_model=TouristPulseResponse)
async def get_tourist_outlook(
    location: str = Query(default="Santa Cruz"),
    days: int = Query(default=30, ge=1, le=60),
    db: Session = Depends(get_db),
):
    """
    Get tourist demand outlook for a location.

    Integrates:
    - Open-Meteo weather API (forecast window is limited; we degrade gracefully beyond it)
    - TomTom traffic API (optional, falls back to mock)
    - Local events CSV (optional)
    - DeepSeek via OpenRouter for demand analysis (optional, falls back to heuristic)
    """
    logger.info(f"Tourist outlook requested for {location}, {days} days")

    try:
        # Fetch external data (weather is forecast-limited internally)
        weather_data = await fetch_weather_data(days)
        traffic_data = await fetch_traffic_data()
        events = load_events()

        outlook: List[TouristPulseOutlook] = []
        start_date = date.today()

        available_dates = weather_data.get("daily", {}).get("time", []) or []
        available_set = set(available_dates)

        # Create an outlook for each requested day
        for i in range(days):
            current_date = start_date + timedelta(days=i)
            date_str = current_date.isoformat()

            day_events = [e for e in events if e.get("date") == date_str]

            # If the day is within forecast window, use real forecast; else baseline
            if date_str in available_set:
                idx = weather_data["daily"]["time"].index(date_str)

                daily_weather = {
                    "weathercode": weather_data["daily"]["weathercode"][idx],
                    "temp_max": weather_data["daily"]["temperature_2m_max"][idx],
                    "temp_min": weather_data["daily"]["temperature_2m_min"][idx],
                    "precipitation_probability": (
                        weather_data["daily"].get("precipitation_probability_max", [0])[idx]
                        if "precipitation_probability_max" in weather_data["daily"]
                        else 0
                    ),
                }

                weather_condition = get_weather_condition(int(daily_weather["weathercode"]))

                prediction = await call_llm_for_prediction(
                    date_str,
                    {
                        "condition": weather_condition,
                        "temp_max": daily_weather["temp_max"],
                        "temp_min": daily_weather["temp_min"],
                        "precipitation_probability": daily_weather["precipitation_probability"],
                    },
                    traffic_data,
                    day_events,
                )

                level_map = {
                    "low": "low",
                    "normal": "moderate",
                    "high": "high",
                    "very high": "very_high",
                }
                demand_level = level_map.get(prediction.get("level", "normal"), "moderate")

                signals: List[DemandSignal] = [
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

                # include traffic signal even if congestionLevel is 0.0
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

            else:
                # Beyond forecast horizon: baseline outlook with explicit lower confidence
                baseline_signals: List[DemandSignal] = []
                if day_events:
                    baseline_signals.append(
                        DemandSignal(
                            source="events",
                            factor=f"{len(day_events)} event(s)",
                            impact="positive",
                            weight=0.4,
                        )
                    )
                baseline_signals.append(
                    DemandSignal(
                        source="forecast",
                        factor="beyond_forecast_window",
                        impact="neutral",
                        weight=0.0,
                    )
                )

                outlook.append(
                    TouristPulseOutlook(
                        date=current_date,
                        demand_level="moderate",
                        confidence=0.35 if not day_events else 0.45,
                        drivers=baseline_signals,
                        summary="Beyond the reliable weather forecast window; showing baseline demand with lower confidence.",
                    )
                )

        return TouristPulseResponse(
            location=location,
            outlook=outlook,
            generated_at=datetime.utcnow().isoformat(),
        )

    except HTTPException as e:
        logger.error(f"HTTPException in tourist outlook: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Failed to generate tourist outlook: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate outlook: {type(e).__name__}: {str(e)}. Check backend logs for details.",
        )
