import csv
import json
from typing import Any, Dict, Iterable, List, Optional, Set

from app.services.deepseek_client import call_deepseek


# -----------------------------
# Shopline Businesses (CSV + Classifications + Gemini)
# -----------------------------


def _extract_first_json_object(text: str) -> Optional[str]:
    """Return the first JSON object substring found in text (naive brace matching)."""
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


def _norm(s: Any) -> str:
    return str(s).strip() if s is not None else ""


def _norm_lower(s: Any) -> str:
    return _norm(s).lower()


# Common synonym/normalization map to make search friendlier.
# Keep this intentionally small and local for hackathon use.
_QUERY_SYNONYMS = {
    "bookstore": "book",
    "book store": "book",
    "coffee shop": "coffee",
    "cafe": "coffee",
    "café": "coffee",
    "restaurant": "food",
    "restaurants": "food",
}


from typing import List  # already imported, but for clarity in this context

def _normalize_query(q: str) -> List[str]:
    """Normalize a free-text query into tokens with a few light synonyms."""
    ql = (q or "").strip().lower()
    if not ql:
        return []

    # Apply phrase-level synonyms first
    for k, v in _QUERY_SYNONYMS.items():
        if k in ql:
            ql = ql.replace(k, v)

    # Split on whitespace and punctuation-ish characters
    tokens = []
    for part in ql.replace("/", " ").replace("-", " ").replace("&", " ").split():
        t = part.strip()
        if not t:
            continue
        # light stemming for plural 's'
        if len(t) > 3 and t.endswith("s"):
            t = t[:-1]
        tokens.append(t)

    # de-dupe while preserving order
    seen = set()
    return [t for t in tokens if not (t in seen or seen.add(t))]


def load_business_catalog_from_csv(csv_path: str) -> List[Dict[str, Any]]:
    """Load businesses from CSV.

    Supports headers (case-insensitive):
      - Business Name OR name
      - Location OR location
      - Classification OR classification OR category

    Optional headers:
      - description
      - categories (comma-separated)

    Returns a list of dicts with keys:
      name, location, classification, description, categories
    """
    out: List[Dict[str, Any]] = []

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return out

        # Normalize headers (handles UTF-8 BOM and stray whitespace)
        def _clean_header(h: Any) -> str:
            # Some CSVs include a UTF-8 BOM on the first header
            return _norm_lower(str(h).lstrip("\ufeff"))

        field_map = {h: _clean_header(h) for h in reader.fieldnames}

        def get_any(r: Dict[str, Any], keys: List[str]) -> str:
            for k in keys:
                v = r.get(k)
                if v is not None and _norm(v) != "":
                    return str(v)
            return ""

        for row in reader:
            r = {field_map.get(k, _norm_lower(k)): v for k, v in row.items()}

            name = _norm(get_any(r, ["business name", "name"]))
            if not name:
                continue

            location = _norm(get_any(r, ["location"]))
            classification = _norm(get_any(r, ["classification", "category"]))
            description = _norm(get_any(r, ["description"]))

            # categories: explicit column, else derive a basic category from classification
            raw_categories = get_any(r, ["categories"])  # comma-separated
            categories = (
                [c.strip().lower() for c in str(raw_categories).split(",") if c.strip()]
                if raw_categories
                else []
            )

            if classification:
                categories.append(classification.strip().lower())

            # de-dupe while preserving order
            seen = set()
            categories = [c for c in categories if not (c in seen or seen.add(c))]

            out.append(
                {
                    "name": name,
                    "location": location,
                    "classification": classification,
                    "description": description,
                    "categories": categories,
                    "_raw": r,
                }
            )

    return out


def get_available_classifications(businesses: Iterable[Dict[str, Any]]) -> List[str]:
    """Return unique classifications (for UI chips / dropdown).

    Sorted alphabetically, with empty/unknown removed.
    """
    vals: Set[str] = set()
    for b in businesses:
        c = _norm(b.get("classification"))
        if c:
            vals.add(c)
    return sorted(vals, key=lambda x: x.lower())


def _matches_classification(b: Dict[str, Any], desired: str) -> bool:
    """Case-insensitive partial match against business classification."""
    desired_l = desired.strip().lower()
    if not desired_l:
        return True
    c = _norm_lower(b.get("classification"))
    return desired_l in c


def filter_businesses(
    businesses: List[Dict[str, Any]],
    classifications: Optional[List[str]] = None,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter businesses by selected classifications and/or free-text query."""
    selected = [s.strip() for s in (classifications or []) if str(s).strip()]
    q_tokens = _normalize_query(query or "")

    out: List[Dict[str, Any]] = []
    for b in businesses:
        if selected:
            if not any(_matches_classification(b, s) for s in selected):
                continue

        if q_tokens:
            hay = " ".join(
                [
                    _norm_lower(b.get("name")),
                    _norm_lower(b.get("location")),
                    _norm_lower(b.get("classification")),
                    _norm_lower(b.get("description")),
                ]
            )

            # Require ALL tokens to appear somewhere in the combined text.
            # This makes queries like "bookstore" -> ["book"] match "Bookshop Santa Cruz".
            if any(t not in hay for t in q_tokens):
                continue

        out.append(b)

    return out


def _alphabetical_fallback(businesses: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    ranked = list(businesses)
    ranked.sort(key=lambda x: _norm_lower(x.get("name")))
    return ranked[: max(1, min(int(limit), 50))]


def recommend_businesses_via_gemini(
    businesses: List[Dict[str, Any]],
    classifications: Optional[List[str]] = None,
    query: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Use Gemini 1.5 to rank businesses based on user-selected classifications and free-text intent.

    This is designed for the UI pattern:
      - User can click a classification chip (e.g., "Food & Drink", "Retail") OR type what they want.

    Expected Gemini response (best-effort):
      {"ranked_names": ["Business A", "Business B", ...]}

    Falls back to alphabetical order on any failure.
    """
    if not businesses:
        return []

    pool = filter_businesses(businesses, classifications=classifications, query=query)
    if not pool:
        pool = businesses

    # Keep prompt bounded
    pre = _alphabetical_fallback(pool, limit=max(20, int(limit) * 2))

    prompt_payload = {
        "task": "Rank local businesses for a user based on classification filters and free-text intent.",
        "preferences": {
            "classifications": classifications or [],
            "query": query or "",
            "limit": max(1, min(int(limit), 50)),
        },
        "businesses": [
            {
                "name": b.get("name"),
                "location": b.get("location"),
                "classification": b.get("classification"),
                "description": b.get("description"),
            }
            for b in pre
        ],
        "output_format": {"ranked_names": ["string (business name)"]},
        "instructions": "Return JSON only. ranked_names must be a list of names from the provided businesses.",
    }

    prompt = "Return JSON only.\n\n" + json.dumps(prompt_payload, ensure_ascii=False)

    try:
        # NOTE: Uses shared API key; Gemini 1.5 is routed behind call_deepseek in this repo
        raw = call_deepseek(
            messages=[{"role": "user", "content": prompt}],
        ).strip()
        obj = _extract_first_json_object(raw)
        if not obj:
            return _alphabetical_fallback(pre, limit)
        data = json.loads(obj)
        ranked_names = data.get("ranked_names") or []
        ranked_names = [str(x).strip() for x in ranked_names if str(x).strip()]
        if not ranked_names:
            return _alphabetical_fallback(pre, limit)

        by_name = {str(b.get("name")).strip().lower(): b for b in pre}
        ranked: List[Dict[str, Any]] = []
        used = set()
        for n in ranked_names:
            k = n.strip().lower()
            b = by_name.get(k)
            if b and k not in used:
                ranked.append(b)
                used.add(k)
            if len(ranked) >= max(1, min(int(limit), 50)):
                break

        # Fill remaining slots alphabetically
        if len(ranked) < max(1, min(int(limit), 50)):
            for b in _alphabetical_fallback(pre, limit=50):
                k = str(b.get("name")).strip().lower()
                if k in used:
                    continue
                ranked.append(b)
                used.add(k)
                if len(ranked) >= max(1, min(int(limit), 50)):
                    break

        return ranked

    except Exception:
        return _alphabetical_fallback(pre, limit)
