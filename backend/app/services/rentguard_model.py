
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from typing import Dict, List, Optional, Tuple

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# You asked us to assume the standard deviation of price inflation is ~0.3
DEFAULT_YOY_STD_PCT: float = 0.3


@dataclass(frozen=True)
class RentGuardBaseline:
    slope_per_year: float
    intercept: float
    year_min: int
    year_max: int
    mean_yoy_pct: float
    std_yoy_pct: float


def _least_squares_fit(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    """Fit y = a*x + b via least squares. Returns (a, b)."""
    n = len(xs)
    if n < 2:
        raise ValueError("Need at least 2 points to fit a line")

    x_mean = sum(xs) / n
    y_mean = sum(ys) / n

    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        # All x are the same year; default to flat line through mean
        return 0.0, y_mean

    a = num / den
    b = y_mean - a * x_mean
    return a, b


def _normalize_header(h: str) -> str:
    return (h or "").strip().lower()


def _parse_csv(path: Path) -> Tuple[List[int], List[float], List[float]]:
    """Parse CSV into years, prices, yoy%. yoy% may be empty -> [] values filled with None."""
    years: List[int] = []
    prices: List[float] = []
    yoy: List[float] = []

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")

        headers = {_normalize_header(h): h for h in reader.fieldnames}

        # Flexible column names
        year_col = headers.get("year")

        # Allow deriving year from a date-like column (common in event spreadsheets)
        date_col = (
            headers.get("date")
            or headers.get("event_date")
            or headers.get("start_date")
            or headers.get("start")
        )

        # Flexible target column names (land-equivalent / rent proxy)
        price_col = (
            headers.get("avg_land_price_usd")
            or headers.get("avg_land_price")
            or headers.get("avg_monthly_rent_usd")
            or headers.get("avg_rent")
            or headers.get("rent")
            or headers.get("price")
        )

        yoy_col = headers.get("land_yoy_pct") or headers.get("yoy_pct")

        if not price_col:
            raise ValueError(
                f"CSV missing a usable target column. Expected one of: avg_land_price_usd, avg_land_price, avg_monthly_rent_usd, avg_rent, rent, price. Got: {reader.fieldnames}"
            )

        if not year_col and not date_col:
            raise ValueError(
                f"CSV missing 'year' and no date-like column to derive year. Got: {reader.fieldnames}"
            )

        for row in reader:
            # Year can come directly from a year column, or be derived from a date column
            y_raw = row.get(year_col) if year_col else None
            if (y_raw is None or str(y_raw).strip() == "") and date_col:
                d_raw = row.get(date_col)
                if d_raw is None or str(d_raw).strip() == "":
                    continue
                # Try a few common formats
                d_str = str(d_raw).strip()
                year_val = None
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        year_val = datetime.strptime(d_str[:19], fmt).year
                        break
                    except Exception:
                        pass
                if year_val is None:
                    # As a last resort, take first 4 digits if they look like a year
                    if len(d_str) >= 4 and d_str[:4].isdigit():
                        year_val = int(d_str[:4])
                if year_val is None:
                    continue
                y = year_val
            else:
                if y_raw is None or str(y_raw).strip() == "":
                    continue
                y = int(float(str(y_raw).strip()))

            p_raw = row.get(price_col)
            if p_raw is None or str(p_raw).strip() == "":
                continue

            years.append(int(y))
            prices.append(float(str(p_raw).strip()))

            if yoy_col:
                v = row.get(yoy_col)
                if v is None or str(v).strip() == "":
                    continue
                yoy.append(float(str(v).strip()))

    if len(years) < 2:
        raise ValueError(f"Not enough data rows in CSV: {path}")

    return years, prices, yoy


def _embedded_fallback_series() -> Tuple[List[int], List[float], List[float]]:
    """Fallback 2015–2024 land-equivalent series (demo-safe)."""
    data = [
        (2015, 2100.0, 4.8),
        (2016, 2200.0, 4.9),
        (2017, 2305.0, 4.8),
        (2018, 2415.0, 4.9),
        (2019, 2530.0, 4.8),
        (2020, 2480.0, -2.0),
        (2021, 2620.0, 5.6),
        (2022, 2850.0, 8.8),
        (2023, 3100.0, 8.7),
        (2024, 3350.0, 7.0),
    ]
    years = [y for y, _, _ in data]
    prices = [p for _, p, _ in data]
    yoy = [v for _, _, v in data]
    return years, prices, yoy


def _discover_csv_path() -> Optional[Path]:
    """Try common CSV locations in this repo."""
    # rentguard_model.py is at backend/app/services/rentguard_model.py
    backend_dir = Path(__file__).resolve().parents[2]
    candidates = [
        backend_dir / "data" / "santa_cruz_land_prices.csv",
        backend_dir / "data" / "santa_cruz_land_equivalent.csv",
        backend_dir / "data" / "santa_cruz_rent_by_unit.csv",  # if you later expand
        backend_dir / "data" / "santa_cruz_events_combined.csv",  # primary training spreadsheet
        backend_dir / "santa_cruz_events_combined.csv",           # fallback if stored at backend root
        backend_dir / "santa_cruz_avg_rent&increase.csv",          # legacy name
    ]

    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


def _build_baseline() -> RentGuardBaseline:
    csv_path = _discover_csv_path()

    if csv_path:
        try:
            years, prices, yoy = _parse_csv(csv_path)
            logger.info(f"RentGuard baseline loaded from CSV: {csv_path}")
        except Exception as e:
            logger.warning(f"RentGuard baseline CSV parse failed ({csv_path}); using fallback series. Error: {e}")
            years, prices, yoy = _embedded_fallback_series()
    else:
        logger.warning("RentGuard baseline CSV not found; using fallback series")
        years, prices, yoy = _embedded_fallback_series()

    xs = [float(y) for y in years]
    ys = prices

    slope, intercept = _least_squares_fit(xs, ys)

    year_min = min(years)
    year_max = max(years)

    mean_yoy = sum(yoy) / len(yoy) if yoy else 0.0

    return RentGuardBaseline(
        slope_per_year=float(slope),
        intercept=float(intercept),
        year_min=int(year_min),
        year_max=int(year_max),
        mean_yoy_pct=float(mean_yoy),
        std_yoy_pct=float(DEFAULT_YOY_STD_PCT),
    )


# Build once at import/startup
_BASELINE: RentGuardBaseline = _build_baseline()


def predict_expected_land_price(year: int) -> float:
    """Predict the expected land-equivalent monthly price for a given year."""
    y = float(year)
    return _BASELINE.slope_per_year * y + _BASELINE.intercept


def get_baseline() -> Dict[str, float]:
    """Expose baseline coefficients and metadata for debugging / optional API."""
    return {
        "slope_per_year": _BASELINE.slope_per_year,
        "intercept": _BASELINE.intercept,
        "year_min": float(_BASELINE.year_min),
        "year_max": float(_BASELINE.year_max),
        "mean_yoy_pct": _BASELINE.mean_yoy_pct,
        "std_yoy_pct": _BASELINE.std_yoy_pct,
    }


def get_yoy_distribution() -> Tuple[float, float]:
    """Return (mean_yoy_pct, std_yoy_pct). std is assumed per requirements."""
    return _BASELINE.mean_yoy_pct, _BASELINE.std_yoy_pct


def z_score_for_yoy(observed_yoy_pct: float) -> float:
    """Compute a z-score for an observed YoY% relative to the baseline distribution."""
    mean, std = get_yoy_distribution()
    if std <= 0:
        return 0.0
    return (float(observed_yoy_pct) - float(mean)) / float(std)
