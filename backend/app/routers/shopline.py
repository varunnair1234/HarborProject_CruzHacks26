from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging
import os
from typing import Optional, List

from app.db.session import get_db
from app.schemas.shopline import (
    ShoplineSearchInput,
    ShoplineSearchResponse,
    BusinessProfile,
)

from app.services.shopline_engine import (
    load_business_catalog_from_csv,
    get_available_classifications,
    filter_businesses,
    recommend_businesses_via_gemini,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shopline", tags=["shopline"])


# CSV-backed business catalog (hackathon-ready)
# Set SHOPLINE_CSV_PATH to point to your CSV file.
# Expected columns (case-insensitive):
#   name, location, classification, description, categories
SHOPLINE_CSV_PATH = os.getenv("SHOPLINE_CSV_PATH", "")


def _resolve_shopline_csv_path() -> str:
    """Resolve a usable CSV path."""
    candidates = []
    if SHOPLINE_CSV_PATH:
        candidates.append(SHOPLINE_CSV_PATH)

    # backend/app/data
    candidates.append(
        os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "data", "shopline_businesses_datafile.csv")
        )
    )

    # backend/path (user-provided location)
    candidates.append(
        os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "path", "shopline_businesses_datafile.csv")
        )
    )

    # project working dir
    candidates.append(os.path.normpath(os.path.join(os.getcwd(), "shopline_businesses_datafile.csv")))

    # container/dev convenience
    candidates.append("/mnt/data/shopline_businesses_datafile.csv")
    candidates.append("/mnt/data/shopline_businesses_sample_3_per_letter.csv")

    for p in candidates:
        if p and os.path.exists(p):
            return p
    return ""


_BUSINESS_CATALOG_CACHE: Optional[list] = None


def _get_business_catalog() -> list:
    global _BUSINESS_CATALOG_CACHE

    if _BUSINESS_CATALOG_CACHE is not None:
        return _BUSINESS_CATALOG_CACHE

    csv_path = _resolve_shopline_csv_path()
    if not csv_path:
        raise HTTPException(
            status_code=500,
            detail=(
                "Shopline CSV not found. Set SHOPLINE_CSV_PATH or place "
                "shopline_businesses_datafile.csv in backend/app/data/."
            ),
        )

    try:
        _BUSINESS_CATALOG_CACHE = load_business_catalog_from_csv(csv_path)
        return _BUSINESS_CATALOG_CACHE
    except Exception as e:
        logger.error(f"Failed to load Shopline CSV catalog: {e}")
        raise HTTPException(status_code=500, detail="Failed to load Shopline business catalog")


def _business_to_profile(b: dict) -> BusinessProfile:
    """Format a business into the user-facing template (no reviews yet)."""
    classification = (b.get("classification") or b.get("category") or "Business").strip()

    desc_parts = [f"Classification: {classification}"]
    if b.get("description"):
        desc_parts.append(b.get("description").strip())

    return BusinessProfile(
        name=b.get("name") or "(unknown)",
        category=classification.lower(),
        location=b.get("location") or "(unknown)",
        description=" | ".join(desc_parts),
    )


@router.get("/classifications")
def list_classifications():
    """Return unique business classifications for UI chips/dropdown."""
    businesses = _get_business_catalog()
    return {"classifications": get_available_classifications(businesses)}


@router.post("/search", response_model=ShoplineSearchResponse)
async def search_businesses(search_input: ShoplineSearchInput, db: Session = Depends(get_db)):
    """Search businesses.

    UI can either:
      - pick one/many `classifications` (chips)
      - and/or type a `query`

    This endpoint returns deterministic (alphabetical) results.
    """
    businesses = _get_business_catalog()

    classifications = search_input.classifications or []

    # Back-compat: if UI still sends `category`, treat it as a single classification
    if not classifications and getattr(search_input, "category", None):
        classifications = [search_input.category]

    matched = filter_businesses(
        businesses,
        classifications=classifications,
        query=search_input.query,
    )

    matched.sort(key=lambda x: (str(x.get("name") or "").lower()))

    results = [_business_to_profile(b) for b in matched]

    return ShoplineSearchResponse(
        query=search_input.query or "(all)",
        results=results,
        total=len(results),
    )


@router.post("/recommend", response_model=ShoplineSearchResponse)
async def recommend_businesses(search_input: ShoplineSearchInput, db: Session = Depends(get_db)):
    """Recommend businesses based on selected classifications and/or free-text query."""
    businesses = _get_business_catalog()

    classifications = search_input.classifications or []

    # Back-compat: if UI still sends `category`, treat it as a single classification
    if not classifications and getattr(search_input, "category", None):
        classifications = [search_input.category]

    ranked = recommend_businesses_via_gemini(
        businesses,
        classifications=classifications,
        query=search_input.query,
        limit=10,
    )

    results = [_business_to_profile(b) for b in ranked]

    label = (
        search_input.query
        or (", ".join([c for c in classifications if isinstance(c, str) and c.strip()]) if classifications else "(all)")
        or "(all)"
    )

    return ShoplineSearchResponse(
        query=label,
        results=results,
        total=len(results),
    )

