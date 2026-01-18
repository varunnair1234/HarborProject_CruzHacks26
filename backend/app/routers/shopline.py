from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging
import os
import csv
from typing import Optional, List

from app.db.session import get_db
from app.db.models import Business
from app.schemas.shopline import (
    ShoplineSearchInput,
    ShoplineSearchResponse,
    BusinessProfile,
)

from app.services.shopline_engine import (
    get_available_classifications,
    filter_businesses,
    recommend_businesses_via_gemini,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shopline", tags=["shopline"])


# CSV-backed business catalog (hackathon-ready)
# Direct path to CSV file
CSV_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "shopline_businesses_datafile.csv")

_BUSINESS_CATALOG_CACHE: Optional[list] = None


def _load_business_catalog_from_csv(csv_path: str) -> list:
    """Load and parse the Shopline business CSV file."""
    rows = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Business Name"):
                    # Normalize column names to match what shopline_engine expects
                    rows.append({
                        "name": row.get("Business Name", ""),
                        "location": row.get("Location", ""),
                        "classification": row.get("Classification", ""),
                    })
        logger.info(f"Loaded {len(rows)} businesses from {csv_path}")
        return rows
    except Exception as e:
        logger.error(f"Failed to parse CSV: {e}")
        return []


def _load_businesses_from_database(db: Session) -> list:
    """Load businesses from database and format for Shopline."""
    try:
        businesses = db.query(Business).filter(Business.is_active == True).all()
        result = []
        for business in businesses:
            result.append({
                "name": business.business_name,
                "location": business.address,
                "classification": business.business_type,
            })
        logger.info(f"Loaded {len(result)} businesses from database")
        return result
    except Exception as e:
        logger.error(f"Failed to load businesses from database: {e}")
        return []


def _get_business_catalog(db: Session, force_refresh: bool = False) -> list:
    """Get combined business catalog from CSV and database."""
    global _BUSINESS_CATALOG_CACHE

    if _BUSINESS_CATALOG_CACHE is not None and not force_refresh:
        return _BUSINESS_CATALOG_CACHE

    businesses = []
    
    # Load from CSV (seed data)
    if os.path.exists(CSV_FILE_PATH):
        try:
            csv_businesses = _load_business_catalog_from_csv(CSV_FILE_PATH)
            businesses.extend(csv_businesses)
            logger.info(f"Loaded {len(csv_businesses)} businesses from CSV")
        except Exception as e:
            logger.warning(f"Failed to load CSV: {e}")
    else:
        logger.warning(f"CSV file not found at {CSV_FILE_PATH}, continuing with database only")
    
    # Load from database (new signups)
    try:
        db_businesses = _load_businesses_from_database(db)
        businesses.extend(db_businesses)
        logger.info(f"Loaded {len(db_businesses)} businesses from database")
    except Exception as e:
        logger.warning(f"Failed to load from database: {e}")
    
    if not businesses:
        raise HTTPException(
            status_code=500,
            detail="No businesses found in CSV or database"
        )
    
    # Remove duplicates (by name, case-insensitive)
    seen = set()
    unique_businesses = []
    for business in businesses:
        name_lower = business.get("name", "").strip().lower()
        if name_lower and name_lower not in seen:
            seen.add(name_lower)
            unique_businesses.append(business)
    
    logger.info(f"Total unique businesses: {len(unique_businesses)}")
    _BUSINESS_CATALOG_CACHE = unique_businesses
    return _BUSINESS_CATALOG_CACHE


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
def list_classifications(db: Session = Depends(get_db)):
    """Return unique business classifications for UI chips/dropdown."""
    businesses = _get_business_catalog(db)
    return {"classifications": get_available_classifications(businesses)}


@router.get("/all")
def get_all_businesses(db: Session = Depends(get_db)):
    """Return all businesses from the catalog."""
    businesses = _get_business_catalog(db)
    results = [_business_to_profile(b) for b in businesses]
    results.sort(key=lambda x: (x.name or "").lower())
    return {
        "results": results,
        "total": len(results),
    }


@router.post("/search", response_model=ShoplineSearchResponse)
async def search_businesses(search_input: ShoplineSearchInput, db: Session = Depends(get_db)):
    """Search businesses.

    UI can either:
      - pick one/many `classifications` (chips)
      - and/or type a `query`

    This endpoint returns deterministic (alphabetical) results.
    """
    businesses = _get_business_catalog(db)

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
    businesses = _get_business_catalog(db)

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