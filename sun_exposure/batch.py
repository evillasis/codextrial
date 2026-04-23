"""
Batch CSV processing for the sun exposure calculator.

Input CSV columns (all optional except one of address/lat+lon and one orientation):
  address, lat, lon,
  facade_azimuth, street_angle, cardinal,
  secondary_azimuth, primary_glass_area_m2, secondary_glass_area_m2, store_type,
  altitude_m, operating_hours (e.g. "11,21"), street_side

Output CSV columns (one row per input row):
  address, lat, lon, facade_azimuth,
  annual_hours, peak_month, peak_daily_hours,
  weighted_score, vertical_irradiance_kwh_m2_year,
  risk_level, protect, film_type,
  error
"""

from __future__ import annotations

import csv
import io
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .building import Building, ObstructionProfile, StoreProfile, facade_from_cardinal, facade_from_street_angle
from .exposure import ExposureCalculator
from .recommendation import recommend_protection
from .geo import geocode, get_elevation, get_street_angle, GeoLookupError
from .geo._ratelimit import TokenBucketLimiter

_NOMINATIM_LIMITER = TokenBucketLimiter(rate=1.0)
_OVERPASS_LIMITER = TokenBucketLimiter(rate=2.0)

OUTPUT_FIELDNAMES = [
    "address", "lat", "lon", "facade_azimuth",
    "annual_hours", "peak_month", "peak_daily_hours",
    "weighted_score", "vertical_irradiance_kwh_m2_year",
    "risk_level", "protect", "film_type",
    "error",
]


def _row_to_buildings(row: dict[str, str]) -> tuple[list[Building], StoreProfile]:
    """Parse one CSV row into a list of Building objects and a StoreProfile."""
    address = row.get("address", "").strip()

    # Resolve coordinates
    lat_s = row.get("lat", "").strip()
    lon_s = row.get("lon", "").strip()
    if lat_s and lon_s:
        lat, lon = float(lat_s), float(lon_s)
    elif address:
        _NOMINATIM_LIMITER.acquire()
        result = geocode(address)
        lat, lon = result["lat"], result["lon"]
    else:
        raise ValueError("Each row needs 'address' or both 'lat' and 'lon'.")

    # Resolve orientation
    facade_az_s = row.get("facade_azimuth", "").strip()
    street_angle_s = row.get("street_angle", "").strip()
    cardinal_s = row.get("cardinal", "").strip()
    street_side = row.get("street_side", "both").strip() or "both"

    if facade_az_s:
        buildings = [Building(lat, lon, float(facade_az_s), address)]
    elif street_angle_s:
        buildings = facade_from_street_angle(lat, lon, float(street_angle_s), street_side, address)
    elif cardinal_s:
        buildings = [facade_from_cardinal(lat, lon, cardinal_s, address)]
    else:
        _OVERPASS_LIMITER.acquire()
        angle = get_street_angle(lat, lon)
        if angle is None:
            raise ValueError("No road found near coordinates. Provide facade_azimuth, street_angle, or cardinal.")
        buildings = facade_from_street_angle(lat, lon, angle, street_side, address)

    # Esquinera / glass area
    sec_az_s = row.get("secondary_azimuth", "").strip()
    p_area_s = row.get("primary_glass_area_m2", "").strip()
    s_area_s = row.get("secondary_glass_area_m2", "").strip()
    store_type = row.get("store_type", "medianera").strip() or "medianera"

    for b in buildings:
        if p_area_s:
            b.primary_glass_area_m2 = float(p_area_s)
        if sec_az_s:
            b.secondary_facade_azimuth = float(sec_az_s) % 360
        if s_area_s:
            b.secondary_glass_area_m2 = float(s_area_s)

    # Altitude
    alt_s = row.get("altitude_m", "").strip()
    altitude_m = float(alt_s) if alt_s else 0.0

    # Operating hours
    oh_s = row.get("operating_hours", "").strip()
    if oh_s:
        parts = [float(x) for x in oh_s.split(",")]
        operating_hours = (parts[0], parts[1])
    else:
        operating_hours = (0.0, 24.0)

    profile = StoreProfile(
        altitude_m=altitude_m,
        operating_hours=operating_hours,
        store_type=store_type,
    )
    return buildings, profile


def _process_row(
    row: dict[str, str],
    calc: ExposureCalculator,
    config: dict[str, Any],
) -> list[dict[str, str]]:
    """Return one or more output dicts for a single CSV input row."""
    try:
        buildings, profile = _row_to_buildings(row)
    except Exception as exc:
        return [_error_row(row, exc)]

    output_rows = []
    for building in buildings:
        try:
            result = calc.calculate(building, profile)
            rec = recommend_protection(result, config=config)
            output_rows.append({
                "address": building.address,
                "lat": f"{building.latitude:.6f}",
                "lon": f"{building.longitude:.6f}",
                "facade_azimuth": f"{building.facade_azimuth:.1f}",
                "annual_hours": f"{result.annual_hours:.0f}",
                "peak_month": str(result.peak_month),
                "peak_daily_hours": f"{result.peak_daily_hours:.1f}",
                "weighted_score": f"{result.weighted_score:.3f}",
                "vertical_irradiance_kwh_m2_year": f"{result.vertical_irradiance_kwh_m2_year:.1f}",
                "risk_level": rec.level,
                "protect": "YES" if rec.protect else "NO",
                "film_type": rec.film_type,
                "error": "",
            })
        except Exception as exc:
            output_rows.append(_error_row(row, exc))

    return output_rows


def _error_row(row: dict[str, str], exc: Exception) -> dict[str, str]:
    return {
        "address": row.get("address", ""),
        "lat": row.get("lat", ""),
        "lon": row.get("lon", ""),
        "facade_azimuth": "",
        "annual_hours": "",
        "peak_month": "",
        "peak_daily_hours": "",
        "weighted_score": "",
        "vertical_irradiance_kwh_m2_year": "",
        "risk_level": "",
        "protect": "",
        "film_type": "",
        "error": str(exc),
    }


def process_batch(
    input_path: str,
    output_path: str,
    calc: ExposureCalculator | None = None,
    config: "dict[str, Any] | None" = None,
    max_workers: int = 4,
) -> int:
    """
    Process a CSV file of locations and write results to output_path.

    Returns the number of rows processed (including error rows).
    """
    from .config import load_config
    cfg = config if config is not None else load_config()
    if calc is None:
        calc = ExposureCalculator(config=cfg)

    with open(input_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    futures_map = {}
    results_by_index: dict[int, list[dict]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for idx, row in enumerate(rows):
            fut = pool.submit(_process_row, row, calc, cfg)
            futures_map[fut] = idx

        for fut in as_completed(futures_map):
            idx = futures_map[fut]
            try:
                results_by_index[idx] = fut.result()
            except Exception as exc:
                results_by_index[idx] = [_error_row(rows[idx], exc)]

    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDNAMES)
        writer.writeheader()
        for idx in range(len(rows)):
            for out_row in results_by_index.get(idx, []):
                writer.writerow(out_row)

    return len(rows)
