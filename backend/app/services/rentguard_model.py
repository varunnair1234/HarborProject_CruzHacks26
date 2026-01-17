
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Per project requirement: assume YoY std ~ 0.3 (% points)
DEFAULT_YOY_STD_PCT: float = 0.3


@dataclass(frozen=True)
class RentGuardBaseline:
    slope_per_year: float
    intercept: float
    year_min: int
    year_max: int
    mean_yoy_pct: float
    std_yoy_pct: float
    source_csv: str
    target_column: str


def _normalize_header(h: str) -> str:
    """Normalize header names for robust matching."""
    return (h or "").strip().lower().replace(" ", "_")


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
        # All x identical
        return 0.0, y_mean

    a = num / den
    b = y_mean - a * x_mean
    return float(a), float(b)


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
    """Locate the RentGuard baseline CSV (land / rent time series)."""
    # rentguard_model.py is at backend/app/services/rentguard_model.py
    backend_dir = Path(__file__).resolve().parents[2]

    candidates = [
        # Preferred baseline files (your confirmed source)
        backend_dir / "santa_cruz_avg_rent&increase.csv",
        backend_dir / "santa_cruz_avgrent&increase.csv",

        # If you later move it under backend/data/
        backend_dir / "data" / "santa_cruz_avg_rent&increase.csv",
        backend_dir / "data" / "santa_cruz_avgrent&increase.csv",

        # Optional legacy / alternative baselines
        backend_dir / "data" / "santa_cruz_land_prices.csv",
        backend_dir / "data" / "santa_cruz_land_equivalent.csv",
    ]

    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


def _parse_csv(path: Path) -> Tuple[List[int], List[float], List[float], str]:
    """Parse CSV into (years, target_values, yoy_pct, target_column_name)."""
    years: List[int] = []
    values: List[float] = []
    yoy: List[float] = []

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")

        headers = {_normalize_header(h): h for h in reader.fieldnames}

        year_col = headers.get("year")
        # Allow deriving year from date-like column if needed
        date_col = headers.get("date") or headers.get("event_date") or headers.get("start_date") or headers.get("start")

        # Flexible target column names
        target_col = (
            headers.get("avg_land_price_usd")
            or headers.get("avg_land_price")
            or headers.get("avg_monthly_rent_usd")
            or headers.get("avg_rent")
            or headers.get("rent")
            or headers.get("price")
        )

        yoy_col = headers.get("land_yoy_pct") or headers.get("yoy_pct")

        if not target_col:
            raise ValueError(
                "CSV missing a usable target column. Expected one of: "
                "avg_land_price_usd, avg_land_price, avg_monthly_rent_usd, avg_rent, rent, price. "
                f"Got: {reader.fieldnames}"
            )
        if not year_col and not date_col:
            raise ValueError(
                f"CSV missing 'year' and no date-like column to derive year. Got: {reader.fieldnames}"
            )

        for row in reader:
            # Determine year
            y_raw = row.get(year_col) if year_col else None
            year_val: Optional[int] = None

            if y_raw is not None and str(y_raw).strip() != "":
                try:
                    year_val = int(float(str(y_raw).strip()))
                except Exception:
                    year_val = None
            elif date_col:
                d_raw = row.get(date_col)
                if d_raw is not None and str(d_raw).strip() != "":
                    d_str = str(d_raw).strip()
                    for fmt in (
                        "%Y-%m-%d",
                        "%m/%d/%Y",
                        "%Y/%m/%d",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M:%S",
                    ):
                        try:
                            year_val = datetime.strptime(d_str[:19], fmt).year
                            break
                        except Exception:
                            pass
                    if year_val is None and len(d_str) >= 4 and d_str[:4].isdigit():
                        year_val = int(d_str[:4])

            if year_val is None:
                continue

            # Determine target value
            v_raw = row.get(target_col)
            if v_raw is None or str(v_raw).strip() == "":
                continue

            try:
                v = float(str(v_raw).strip())
            except Exception:
                continue

            years.append(int(year_val))
            values.append(float(v))

            if yoy_col:
                yoy_raw = row.get(yoy_col)
                if yoy_raw is not None and str(yoy_raw).strip() != "":
                    try:
                        yoy.append(float(str(yoy_raw).strip()))
                    except Exception:
                        pass

    if len(years) < 2:
        raise ValueError(f"Not enough usable data rows in CSV: {path}")

    # If YoY isn't provided, compute it from year-sorted values
    if not yoy and len(values) >= 2:
        pairs = sorted(zip(years, values), key=lambda t: t[0])
        years_sorted = [p[0] for p in pairs]
        values_sorted = [p[1] for p in pairs]
        yoy_vals: List[float] = []
        for i in range(1, len(values_sorted)):
            prev = values_sorted[i - 1]
            cur = values_sorted[i]
            yoy_vals.append(((cur - prev) / prev) * 100.0 if prev > 0 else 0.0)
        return years_sorted, values_sorted, yoy_vals, headers.get(_normalize_header(target_col), target_col)

    return years, values, yoy, target_col


def _build_baseline() -> RentGuardBaseline:
    csv_path = _discover_csv_path()

    if csv_path:
        try:
            years, values, yoy, target_col = _parse_csv(csv_path)
            logger.info(f"RentGuard baseline loaded from CSV: {csv_path}")
        except Exception as e:
            logger.warning(
                f"RentGuard baseline CSV parse failed ({csv_path}); using fallback series. Error: {e}"
            )
            years, values, yoy = _embedded_fallback_series()
            target_col = "fallback_series"
            csv_path = None
    else:
        logger.warning("RentGuard baseline CSV not found; using fallback series")
        years, values, yoy = _embedded_fallback_series()
        target_col = "fallback_series"

    xs = [float(y) for y in years]
    slope, intercept = _least_squares_fit(xs, values)

    mean_yoy = (sum(yoy) / len(yoy)) if yoy else 0.0

    return RentGuardBaseline(
        slope_per_year=float(slope),
        intercept=float(intercept),
        year_min=int(min(years)),
        year_max=int(max(years)),
        mean_yoy_pct=float(mean_yoy),
        std_yoy_pct=float(DEFAULT_YOY_STD_PCT),
        source_csv=str(csv_path) if csv_path else "embedded_fallback",
        target_column=str(target_col),
    )


# =====================
# TRAINING (runs at import)
# =====================
_BASELINE: RentGuardBaseline = _build_baseline()


def predict_expected_land_price(year: int) -> float:
    """Predict the expected baseline (land/rent proxy) for a given year."""
    y = float(year)
    return _BASELINE.slope_per_year * y + _BASELINE.intercept


def get_baseline() -> Dict[str, float | str]:
    """Expose baseline coefficients and metadata for debugging."""
    return {
        "slope_per_year": _BASELINE.slope_per_year,
        "intercept": _BASELINE.intercept,
        "year_min": float(_BASELINE.year_min),
        "year_max": float(_BASELINE.year_max),
        "mean_yoy_pct": _BASELINE.mean_yoy_pct,
        "std_yoy_pct": _BASELINE.std_yoy_pct,
        "source_csv": _BASELINE.source_csv,
        "target_column": _BASELINE.target_column,
    }


def get_yoy_distribution() -> Tuple[float, float]:
    """Return (mean_yoy_pct, std_yoy_pct). std is assumed per requirements."""
    return _BASELINE.mean_yoy_pct, _BASELINE.std_yoy_pct


def z_score_for_yoy(observed_yoy_pct: float) -> float:
    """Compute z-score for an observed YoY% relative to baseline distribution."""
    mean, std = get_yoy_distribution()
    if std <= 0:
        return 0.0
    return (float(observed_yoy_pct) - float(mean)) / float(std)


def is_using_fallback() -> bool:
    """True if the model is using the embedded fallback series."""
    return _BASELINE.source_csv == "embedded_fallback"
