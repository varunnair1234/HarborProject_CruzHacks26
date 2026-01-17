import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from backend.app.services.gemini_client import generate_text
from backend.app.services.events_ingest_downtown import RawEvent


CANONICAL_CATEGORIES: List[str] = [
    "music",
    "art",
    "dance",
    "food",
    "theatre",
    "comedy",
    "family",
    "outdoors",
    "community",
    "education",
    "nightlife",
    "market",
]


@dataclass
class Event:
    id: str
    title: str
    description: str
    start_time_text: str
    location: str
    url: str
    categories: List[str]          # canonical
    source: str


def normalize_event_categories(title: str, description: str) -> List[str]:
    """
    Gemini Flash: map free text -> subset of CANONICAL_CATEGORIES
    Returns up to 3 categories.
    """
    allowed = ", ".join(CANONICAL_CATEGORIES)

    prompt = f"""
You are categorizing an event into a SMALL fixed set of categories.

Allowed categories: [{allowed}]

Event title: {title}
Event description: {description}

Rules:
- Choose ONLY from the allowed categories.
- Return at most 3 categories.
- Return ONLY valid JSON in this format: {{"categories": ["music","art"]}}
"""

    raw = generate_text(prompt).strip()
    categories = _safe_extract_categories_json(raw)
    # sanitize
    categories = [c for c in categories if c in CANONICAL_CATEGORIES]
    return categories[:3]


def expand_user_query(selected_categories: List[str], user_text: Optional[str] = None) -> List[str]:
    """
    Gemini Flash: expand user's categories + optional free text into "tags" (still canonical-only here).
    Keep it simple: return expanded canonical categories.
    """
    allowed = ", ".join(CANONICAL_CATEGORIES)
    selected = [c for c in selected_categories if c in CANONICAL_CATEGORIES]

    prompt = f"""
You help expand a user's interest for event recommendations.

Allowed categories: [{allowed}]
User selected categories: {selected}
User additional text (may be empty): {user_text or ""}

Return:
- A list of categories from the allowed set that should be considered relevant
- Include the selected categories, plus closely related ones if justified

Return ONLY JSON: {{"expanded_categories": ["music","nightlife"]}}
"""

    raw = generate_text(prompt).strip()
    expanded = _safe_extract_key_as_list(raw, "expanded_categories")
    expanded = [c for c in expanded if c in CANONICAL_CATEGORIES]

    # Always include original selection
    out = list(dict.fromkeys(selected + expanded))
    return out


def build_event_from_raw(raw: RawEvent, categories: List[str]) -> Event:
    return Event(
        id=f"{raw.source}:{raw.source_id}",
        title=raw.title,
        description=raw.description,
        start_time_text=raw.start_time_text,
        location=raw.location,
        url=raw.url,
        categories=categories,
        source=raw.source,
    )


def recommend_events(
    events: List[Event],
    selected_categories: List[str],
    user_text: Optional[str] = None,
    limit: int = 10,
) -> List[Event]:
    """
    Deterministic, explainable ranking:
      score = (#overlap between expanded user categories and event categories,
               -len(event.categories))
    Filters out 0-overlap.
    """
    expanded = set(expand_user_query(selected_categories, user_text=user_text))

    scored: List[Tuple[Tuple[int, int], Event]] = []
    for e in events:
        overlap = len(expanded.intersection(set(e.categories)))
        if overlap <= 0:
            continue
        score = (overlap, -len(e.categories))
        scored.append((score, e))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]


# -----------------------
# JSON helpers (robust-ish)
# -----------------------

def _safe_extract_categories_json(raw: str) -> List[str]:
    # Find the first {...} block to avoid extra text
    obj = _extract_first_json_object(raw)
    if not obj:
        return []
    try:
        data = json.loads(obj)
        cats = data.get("categories", [])
        return cats if isinstance(cats, list) else []
    except Exception:
        return []


def _safe_extract_key_as_list(raw: str, key: str) -> List[str]:
    obj = _extract_first_json_object(raw)
    if not obj:
        return []
    try:
        data = json.loads(obj)
        val = data.get(key, [])
        return val if isinstance(val, list) else []
    except Exception:
        return []


def _extract_first_json_object(text: str) -> Optional[str]:
    # naive brace matching
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None
