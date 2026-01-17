from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
from collections import defaultdict
import logging
import httpx
import json
import csv
import os
import asyncio
import re
from typing import List, Dict, Any

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

# NWS API base URL
NWS_BASE = "https://api.weather.gov"

# NWS typically provides ~7 days of forecast
NWS_MAX_DAYS = 7


def clamp_days(days: int) -> int:
    """Clamp days to NWS allowed range."""
    if days is None:
        return 7
    return max(1, min(int(days), NWS_MAX_DAYS))


def _nws_user_agent() -> str:
    # NWS requires a User-Agent. If you add `nws_user_agent` to settings later, we’ll use it.
    ua = getattr(settings, "nws_user_agent", None)
    if ua and isinstance(ua, str) and ua.strip():
        return ua.strip()
    return "HarborProject_CruzHacks26 (contact: none)"


async def nws_get_json(url: str) -> dict:
    """Fetch JSON from NWS API with required headers."""
    headers = {
        "User-Agent": _nws_user_agent(),
        "Accept": "application/geo+json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


async def fetch_weather_data_nws(lat: float, lon: float) -> dict:
    """Fetch weather data from NWS API (2-step: points -> forecast)."""
    try:
        points = await nws_get_json(f"{NWS_BASE}/points/{lat},{lon}")
        forecast_url = points["properties"]["forecast"]
        logger.info("NWS points resolved to forecast URL: %s", forecast_url)

        forecast = await nws_get_json(forecast_url)
        logger.info("Successfully fetched NWS forecast data")
        return forecast

    except httpx.TimeoutException as e:
        logger.error("NWS API timeout: %s", e)
        raise HTTPException(status_code=502, detail="NWS Weather API request timed out")
    except httpx.HTTPStatusError as e:
        logger.error("NWS API HTTP error: %s - %s", e.response.status_code, e.response.text)
        raise HTTPException(status_code=502, detail=f"NWS Weather API error: {e.response.status_code}")
    except KeyError as e:
        logger.error("NWS API response missing expected field: %s", e)
        raise HTTPException(status_code=502, detail=f"NWS API response missing field: {e}")
    except Exception as e:
        logger.error("Failed to fetch NWS weather data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch weather data: {str(e)}")


def nws_periods_to_daily(periods: List[dict], days: int) -> List[dict]:
    """Convert NWS forecast periods into daily summaries."""
    from datetime import date
    
    today = date.today()
    grouped = defaultdict(list)
    for p in periods:
        start_time = p.get("startTime")
        if not start_time:
            continue

        try:
            if start_time.endswith("Z"):
                dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(start_time)
        except Exception:
            continue

        period_date = dt.date()
        # Only include dates from today onwards (filter out past dates)
        if period_date >= today:
            grouped[period_date].append(p)

    daily: List[dict] = []
    # Sort dates and take only future dates, limit to requested days
    sorted_dates = sorted([d for d in grouped.keys() if d >= today])[:days]
    for d in sorted_dates:
        ps = grouped[d]

        temps = [p.get("temperature") for p in ps if isinstance(p.get("temperature"), (int, float))]
        max_temp = max(temps) if temps else None
        min_temp = min(temps) if temps else None

        pops: List[float] = []
        for p in ps:
            pop = (p.get("probabilityOfPrecipitation") or {}).get("value")
            if isinstance(pop, (int, float)):
                pops.append(float(pop))
        max_pop = max(pops) if pops else 0.0

        rep = next((p for p in ps if p.get("isDaytime") is True), None) or ps[0]
        condition = rep.get("shortForecast") or rep.get("detailedForecast") or "Unknown"

        daily.append(
            {
                "date": d,
                "temp_max": max_temp,
                "temp_min": min_temp,
                "precip_probability": max_pop,
                "condition": condition,
            }
        )

    return daily


async def fetch_traffic_data() -> Dict[str, Any]:
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


def load_events() -> List[Dict[str, Any]]:
    """Load events from CSV file if present; otherwise return empty."""
    events: List[Dict[str, Any]] = []

    current_file = os.path.abspath(__file__)
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))  # backend/

    possible_paths = [
        os.path.join(backend_dir, "santa_cruz_events_combined.csv"),
        os.path.join(os.getcwd(), "santa_cruz_events_combined.csv"),
        os.path.join(os.getcwd(), "backend", "santa_cruz_events_combined.csv"),
        "santa_cruz_events_combined.csv",
    ]

    for path in possible_paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("name") and row.get("date"):
                        # Strip whitespace from date to ensure proper matching
                        date_str = row["date"].strip()
                        events.append(
                            {
                                "name": row["name"].strip(),
                                "date": date_str,
                                "location": row.get("location", "Santa Cruz").strip(),
                                "type": row.get("type", "community").strip(),
                            }
                        )
            logger.info("✅ Loaded %s events from %s", len(events), os.path.abspath(path))
            return events
        except Exception as e:
            logger.error("Failed to load events from %s: %s", os.path.abspath(path), e, exc_info=True)

    logger.warning("⚠️ No events CSV file found. Predictions will work without event data.")
    return events


def _build_llm_input(date_str: str, location: str, weather: Dict[str, Any], traffic: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    congestion = traffic.get("flow", {}).get("congestionLevel", None)
    
    # Calculate day of week (0=Monday, 6=Sunday)
    date_obj = datetime.fromisoformat(date_str).date()
    day_of_week = date_obj.weekday()  # 0=Monday, 6=Sunday
    is_weekend = day_of_week >= 5  # Saturday (5) or Sunday (6)
    day_name = date_obj.strftime("%A")  # Full day name
    
    return {
        "date": date_str,
        "day_of_week": day_name,
        "is_weekend": is_weekend,
        "location": location,
        "weather": {
            "condition": weather.get("condition"),
            "temp_max_f": weather.get("temp_max"),
            "temp_min_f": weather.get("temp_min"),
            "precip_prob_pct": weather.get("precipitation_probability"),
        },
        "traffic": {
            "congestion_level": congestion,
            "incidents_count": len(traffic.get("incidents", [])),
        },
        "events": [{"name": e.get("name"), "type": e.get("type"), "location": e.get("location")} for e in events],
        "notes": [
            "If surf conditions are not provided, do not invent them. You may only mention surf as a conditional driver (e.g., 'if swell is good')."
        ],
    }


def _normalize_llm_output(prediction: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize output so the rest of the pipeline can continue to use:
    { level, factor, reasoning, confidence }
    Accepts BOTH the old schema and your new schema.
    """
    if not isinstance(prediction, dict):
        return {"level": "normal", "factor": 1.0, "reasoning": "Unable to generate prediction", "confidence": 0.5}

    # New schema -> old schema
    if "demand_level" in prediction:
        dl = (prediction.get("demand_level") or "moderate").strip().lower()
        level = {"low": "low", "moderate": "normal", "high": "high"}.get(dl, "normal")
        reasoning = prediction.get("summary") or "Unable to generate prediction"
        confidence = prediction.get("confidence", 0.6)
        # factor optional; keep it consistent for callers that still display it later
        factor = {"low": 0.85, "normal": 1.0, "high": 1.25}.get(level, 1.0)
        return {
            "level": level,
            "factor": factor,
            "reasoning": reasoning,
            "confidence": float(confidence) if isinstance(confidence, (int, float)) else 0.6,
        }

    # Old schema pass-through
    if "level" in prediction and "reasoning" in prediction:
        conf = prediction.get("confidence", 0.6)
        return {
            "level": prediction.get("level", "normal"),
            "factor": prediction.get("factor", 1.0),
            "reasoning": prediction.get("reasoning", "Unable to generate prediction"),
            "confidence": float(conf) if isinstance(conf, (int, float)) else 0.6,
        }

    return {"level": "normal", "factor": 1.0, "reasoning": "Unable to generate prediction", "confidence": 0.5}


async def call_llm_for_prediction(date_str: str, location: str, weather: Dict[str, Any], traffic: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
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

            return {"level": level, "factor": factor, "reasoning": "Prediction based on weather and events (LLM unavailable)", "confidence": 0.6}

        input_payload = _build_llm_input(date_str, location, weather, traffic, events)
        input_json = json.dumps(input_payload, ensure_ascii=False)

        prompt = f"""<TouristPulseRole>
You are TouristPulse’s demand synthesis engine for Santa Cruz, California.
Your job is to interpret already-collected public signals (weather, events, calendar context) and explain expected visitor activity in a clear, grounded, and practical way.
</TouristPulseRole>

<HardRules>
- Do NOT perform calculations.
- Do NOT invent events, weather, surf conditions, or statistics.
- Do NOT reference private or personal data.
- Do NOT make guarantees or predictions of exact visitor counts.
- Do NOT use promotional or marketing language.
- If signals conflict or confidence is limited, state uncertainty explicitly.
</HardRules>

<AudienceAndTone>
Audience: small business owners and local operators.
Tone: factual, calm, and locally aware.
Style requirements:
- Plain language, no jargon.
- Short sentences.
- Bulleted explanations where appropriate.
- Focus on “why” rather than “what to do.”
</AudienceAndTone>

<TemporalContext>
Day of week significantly impacts tourism in Santa Cruz:
- WEEKENDS (Saturday/Sunday): Expect 30-50% higher baseline tourism. Weekends are prime time for:
  * Day trippers from Bay Area
  * Beach visitors and surfers
  * Boardwalk visitors
  * Weekend getaways
- WEEKDAYS (Monday-Friday): Lower baseline tourism, especially mid-week (Tuesday-Thursday)
- FRIDAY: Transition day - higher than weekdays but lower than weekends
- MONDAY: Often lower due to post-weekend lull

When making predictions:
- If is_weekend=true, start with higher baseline tourism expectation
- Weekend + good weather + events = very high tourism potential
- Weekday + events = moderate tourism (events help but fewer casual visitors)
- Consider that weekend events draw more attendees than weekday events
</TemporalContext>

<EventWeighting>
When evaluating events, weigh them based on expected attendance and draw:

HIGH WEIGHT (Major tourism drivers):
- Santa Cruz Beach Boardwalk events (iconic tourist destination)
- City-wide festivals (e.g., "Downtown Santa Cruz", "Santa Cruz County")
- Major music/arts events at large venues (Civic Auditorium, large theaters)
- Sports events at major venues (Kaiser Permanente Arena)
- Holiday celebrations and large community gatherings

MEDIUM WEIGHT (Moderate tourism impact):
- Farmers markets (regular, local draw)
- Community events at mid-size venues
- Regular cultural events (jazz center, smaller theaters)
- Outdoor activities at state parks (moderate draw)

LOW WEIGHT (Minimal tourism impact):
- Small community gatherings
- Local workshops or classes
- Small markets or niche events
- Events at small venues or private locations

Consider:
- Event name patterns: "Downtown", "County", "Boardwalk" suggest larger scale
- Venue size: Large venues = more attendees
- Event type: Festivals > Music > Sports > Food/Markets > Community
- Multiple events on same day amplify impact
- Weekend events typically draw 2-3x more attendees than weekday events
</EventWeighting>

<Task>
Given the structured input signals below, produce a concise visitor demand outlook for the date provided.

You must:
1) Classify overall visitor activity as exactly one of: ["low", "moderate", "high"]
2) Consider day of week impact: weekends have significantly higher baseline tourism (see TemporalContext above)
3) Weight events appropriately based on their scale and location (see EventWeighting above)
4) Combine temporal context (weekend vs weekday) with weather and events to determine final level
5) Explain the classification using coastal Santa Cruz logic, including surf-driven tourism ONLY if the input supports it.
6) Identify which factors are driving demand up or down, noting which events are major vs minor contributors.
7) Note any uncertainty or conflicting signals honestly.
</Task>

<OutputFormat>
Return ONLY valid JSON. No markdown. No extra text.

Use this exact schema:

{{
  "demand_level": "low" | "moderate" | "high",
  "summary": string,
  "drivers": [string, ...],
  "suppressors": [string, ...],
  "confidence": number,
  "limitations": string
}}

Additional constraints:
- drivers: 2 to 4 items
- suppressors: 0 to 3 items
- Each list item must be one sentence.
- confidence must be between 0.0 and 1.0 and reflect signal alignment.
</OutputFormat>

<InputSignals>
{input_json}
</InputSignals>
"""

        # Retry logic: try up to 3 times with exponential backoff
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:  # Increased timeout
                    response = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {openrouter_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "deepseek/deepseek-chat",
                            "messages": [
                                {"role": "system", "content": "Return ONLY valid JSON. No markdown. No extra text."},
                                {"role": "user", "content": prompt},
                            ],
                            "temperature": 0.3,
                            "max_tokens": 260,
                        },
                    )
                    response.raise_for_status()

                result = response.json()
                content = result["choices"][0]["message"]["content"].strip()

                # Try to parse JSON with multiple strategies
                raw = None
                try:
                    raw = json.loads(content)
                except json.JSONDecodeError:
                    # Strategy 1: Remove markdown code fences
                    if "```json" in content:
                        content = content.split("```json", 1)[1].split("```", 1)[0].strip()
                    elif "```" in content:
                        content = content.split("```", 1)[1].split("```", 1)[0].strip()
                    
                    # Strategy 2: Try to extract JSON object
                    try:
                        raw = json.loads(content)
                    except json.JSONDecodeError:
                        # Strategy 3: Find JSON object in text
                        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
                        if json_match:
                            raw = json.loads(json_match.group(0))
                        else:
                            raise ValueError(f"Could not parse JSON from LLM response: {content[:200]}")

                if raw:
                    return _normalize_llm_output(raw)
                    
            except httpx.TimeoutException as e:
                last_error = f"Timeout (attempt {attempt + 1}/{max_retries})"
                logger.warning("LLM API timeout for %s: %s", date_str, last_error)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                    continue
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                logger.warning("LLM API HTTP error for %s: %s", date_str, last_error)
                # Don't retry on 4xx errors (client errors)
                if 400 <= e.response.status_code < 500:
                    break
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
            except json.JSONDecodeError as e:
                last_error = f"JSON parse error: {str(e)}"
                logger.warning("LLM JSON parse error for %s: %s", date_str, last_error)
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)}"
                logger.warning("LLM API error for %s (attempt %d/%d): %s", date_str, attempt + 1, max_retries, last_error)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue

        # All retries failed
        logger.error("LLM prediction failed for %s after %d attempts. Last error: %s", date_str, max_retries, last_error)
        return {"level": "normal", "factor": 1.0, "reasoning": "Unable to generate prediction", "confidence": 0.5}

    except Exception as e:
        logger.error("LLM prediction failed for %s: %s", date_str, e, exc_info=True)
        return {"level": "normal", "factor": 1.0, "reasoning": "Unable to generate prediction", "confidence": 0.5}


@router.get("/outlook", response_model=TouristPulseResponse)
async def get_tourist_outlook(
    location: str = "Santa Cruz",
    days: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """
    Get tourist demand outlook for a location.

    Notes:
    - NWS API typically provides ~7 days of forecast; requests above that will be clamped.
    """
    requested_days = days
    days = clamp_days(days)

    logger.info("Tourist outlook requested for %s, requested=%s days (clamped=%s)", location, requested_days, days)

    try:
        forecast = await fetch_weather_data_nws(SANTA_CRUZ_LAT, SANTA_CRUZ_LON)
        traffic_data = await fetch_traffic_data()
        events = load_events()

        periods = forecast["properties"]["periods"]
        daily_forecast = nws_periods_to_daily(periods, days)

        if not daily_forecast:
            raise HTTPException(status_code=502, detail="NWS API returned no forecast data")

        outlook: List[TouristPulseOutlook] = []

        # Debug: log all loaded events and their dates
        logger.info("Total events loaded: %d", len(events))
        event_dates_summary = {}
        for e in events:
            event_date = e.get("date", "").strip()
            if event_date:
                if event_date not in event_dates_summary:
                    event_dates_summary[event_date] = []
                event_dates_summary[event_date].append(e.get("name", "Unknown"))
        logger.info("Events by date: %s", {k: len(v) for k, v in event_dates_summary.items()})
        
        for item in daily_forecast:
            current_date = item["date"]
            date_str = current_date.isoformat()
            # Filter events for this date (strip whitespace for comparison)
            day_events = [e for e in events if e.get("date", "").strip() == date_str]
            logger.info("Date %s (type: %s): Found %d events", date_str, type(current_date).__name__, len(day_events))
            if day_events:
                logger.info("  Events for %s: %s", date_str, [e.get("name") for e in day_events])
            else:
                # Check if there are events with similar dates (off by one day)
                for event_date, event_names in event_dates_summary.items():
                    try:
                        event_date_obj = datetime.fromisoformat(event_date).date()
                        days_diff = abs((event_date_obj - current_date).days)
                        if days_diff == 1:
                            logger.warning("  Date %s has no events, but %s has %d events (off by %d day)", 
                                         date_str, event_date, len(event_names), days_diff)
                    except:
                        pass

            weather_condition = item["condition"]
            prediction = await call_llm_for_prediction(
                date_str,
                location,
                {
                    "condition": weather_condition,
                    "temp_max": item["temp_max"],
                    "temp_min": item["temp_min"],
                    "precipitation_probability": item["precip_probability"],
                },
                traffic_data,
                day_events,
            )

            level_map = {"low": "low", "normal": "moderate", "high": "high", "very_high": "very_high"}
            demand_level = level_map.get(prediction.get("level", "normal"), "moderate")

            signals = [
                DemandSignal(
                    source="weather",
                    factor=(weather_condition or "").lower(),
                    impact="positive" if ("clear" in (weather_condition or "").lower() or "sunny" in (weather_condition or "").lower()) else "negative",
                    weight=0.4,
                )
            ]

            if day_events:
                signals.append(DemandSignal(source="events", factor=f"{len(day_events)} event(s)", impact="positive", weight=0.3))

            if traffic_data.get("flow", {}).get("congestionLevel") is not None:
                signals.append(DemandSignal(source="traffic", factor="congestion", impact="positive", weight=0.3))

            outlook.append(
                TouristPulseOutlook(
                    date=current_date,
                    demand_level=demand_level,
                    confidence=float(prediction.get("confidence", 0.6)),
                    drivers=signals,
                    summary=prediction.get("reasoning", f"Tourism level: {demand_level}"),
                )
            )

        return TouristPulseResponse(location=location, outlook=outlook, generated_at=datetime.utcnow().isoformat())

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to generate tourist outlook: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate outlook: {type(e).__name__}: {str(e)}")
