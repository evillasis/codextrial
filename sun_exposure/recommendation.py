"""
3M sun-protection film recommendation.

Thresholds and film names are loaded from config (config.yaml by default).
Pass a custom config dict to recommend_protection() to override for a market.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .exposure import ExposureResult
from .config import DEFAULT_CONFIG, load_config


@dataclass
class Recommendation:
    level: str          # "NONE" | "LOW" | "MODERATE" | "HIGH" | "CRITICAL"
    protect: bool       # True → recommend 3M film
    film_type: str      # suggested product category
    reason: str
    score: float


def recommend_protection(
    result: ExposureResult,
    config: "dict[str, Any] | None" = None,
) -> Recommendation:
    """
    Produce a 3M sun-protection recommendation from an ExposureResult.

    config : optional config dict (from load_config()).  None → bundled defaults.
    """
    cfg = config if config is not None else load_config()
    thresholds = cfg["thresholds"]
    films = cfg["films"]

    daily_score = result.weighted_score / 365

    if daily_score < thresholds["none"]:
        level = "NONE"
    elif daily_score < thresholds["low"]:
        level = "LOW"
    elif daily_score < thresholds["moderate"]:
        level = "MODERATE"
    elif daily_score < thresholds["high"]:
        level = "HIGH"
    else:
        level = "CRITICAL"

    protect = level not in ("NONE", "LOW")
    film_type = films[level.lower()]

    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]

    peak_h = result.monthly_avg_hours[result.peak_month - 1]
    reason = (
        f"Facade faces {result.building.cardinal_direction} "
        f"({result.building.facade_azimuth:.0f}°). "
        f"Peak exposure is {peak_h:.1f} h/day in {month_names[result.peak_month - 1]} "
        f"with {result.annual_hours:.0f} annual direct-sun hours."
    )

    return Recommendation(
        level=level,
        protect=protect,
        film_type=film_type,
        reason=reason,
        score=round(daily_score, 3),
    )


def format_report(
    result: ExposureResult,
    rec: Recommendation,
    version: str = "",
) -> str:
    from . import __version__
    ver = version or __version__
    separator = "=" * 56
    lines = [
        separator,
        f" SUN EXPOSURE & 3M FILM RECOMMENDATION  v{ver}",
        separator,
    ]

    if result.building.address:
        lines.append(f" Address  : {result.building.address}")
    lines += [
        f" Location : {result.building.latitude:.5f}°, {result.building.longitude:.5f}°",
        "",
        " --- Exposure Analysis ---",
        result.summary(),
        "",
        " --- Recommendation ---",
        f" Risk level  : {rec.level}",
        f" Protect?    : {'YES — film recommended' if rec.protect else 'NO — film not necessary'}",
        f" Film type   : {rec.film_type}",
        f" Reason      : {rec.reason}",
    ]

    # Retail context section — only shown when non-default values are present
    context_lines = []

    if result.altitude_m > 0:
        context_lines.append(
            f" Altitude        : {result.altitude_m:.0f} m  "
            f"(intensity factor ×{result.altitude_factor:.2f})"
        )

    oh_start, oh_end = result.operating_hours
    if (oh_start, oh_end) != (0.0, 24.0):
        context_lines.append(
            f" Operating hours : {oh_start:04.1f} – {oh_end:04.1f} local solar time"
        )

    if context_lines:
        lines += ["", " --- Site Context ---"] + context_lines

    lines.append(separator)
    return "\n".join(lines)
