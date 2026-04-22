"""
3M sun-protection film recommendation.

Thresholds are based on industry guidance:
  - >4 h/day peak direct sun → high UV/heat risk, protection strongly recommended
  - 2–4 h/day → moderate, recommended for west/south-facing facades in hot climates
  - <2 h/day → low exposure, usually not necessary

The weighted_score (intensity-adjusted hours) is the primary signal because a
facade that gets 5 h of grazing low-sun is very different from 5 h of high-noon sun.
"""

from dataclasses import dataclass
from .exposure import ExposureResult


@dataclass
class Recommendation:
    level: str          # "NONE" | "LOW" | "MODERATE" | "HIGH" | "CRITICAL"
    protect: bool       # True → recommend 3M film
    film_type: str      # suggested product category
    reason: str
    score: float


LEVELS = {
    "NONE":     (False, "No film needed",          "score < 150"),
    "LOW":      (False, "No film / decorative tint","150 ≤ score < 350"),
    "MODERATE": (True,  "3M Prestige Series (light)","350 ≤ score < 600"),
    "HIGH":     (True,  "3M Prestige Series (medium)","600 ≤ score < 900"),
    "CRITICAL": (True,  "3M Prestige Series (dark) or Ceramic IR","score ≥ 900"),
}


def recommend_protection(result: ExposureResult) -> Recommendation:
    """
    Produce a 3M sun-protection recommendation from an ExposureResult.
    The score used is the intensity-weighted annual score normalised per day.
    """
    daily_score = result.weighted_score / 365

    if daily_score < 0.5:
        level = "NONE"
    elif daily_score < 1.2:
        level = "LOW"
    elif daily_score < 2.2:
        level = "MODERATE"
    elif daily_score < 3.5:
        level = "HIGH"
    else:
        level = "CRITICAL"

    protect, film_type, _ = LEVELS[level]

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


def format_report(result: ExposureResult, rec: Recommendation) -> str:
    separator = "=" * 56
    lines = [
        separator,
        " SUN EXPOSURE & 3M FILM RECOMMENDATION",
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
        separator,
    ]
    return "\n".join(lines)
