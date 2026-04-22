"""
Annual sun exposure calculator.

Samples sun position every hour for every day of the year, accumulates
"effective exposure hours" weighted by sun intensity (sin of elevation).
"""

import math
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

from .solar_position import SolarPosition
from .building import Building


@dataclass
class ExposureResult:
    building: Building
    annual_hours: float          # hours of direct sun on the facade per year
    peak_daily_hours: float      # max direct-sun hours on a single day
    peak_month: int              # month (1–12) with highest average daily exposure
    monthly_avg_hours: list      # [avg daily hours per month], index 0=Jan
    weighted_score: float        # energy-weighted score (accounts for sun intensity)

    def summary(self) -> str:
        month_names = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ]
        lines = [
            f"Facade direction : {self.building.cardinal_direction} "
            f"({self.building.facade_azimuth:.1f}°)",
            f"Annual direct sun: {self.annual_hours:.0f} h/year",
            f"Peak month       : {month_names[self.peak_month - 1]} "
            f"({self.monthly_avg_hours[self.peak_month - 1]:.1f} h/day avg)",
            f"Peak single day  : {self.peak_daily_hours:.1f} h",
            f"Energy score     : {self.weighted_score:.0f}  (intensity-weighted hours)",
        ]
        return "\n".join(lines)


class ExposureCalculator:
    """
    Computes annual sun exposure for a Building.

    Parameters
    ----------
    year        : calendar year to simulate (affects leap-year and exact sun path)
    hour_step   : sampling interval in hours (1 = hourly, 0.5 = every 30 min)
    day_step    : skip every N-th day to speed up (1 = every day, 7 = weekly)
    """

    def __init__(self, year: int = 2025, hour_step: float = 1.0, day_step: int = 1):
        self.year = year
        self.hour_step = hour_step
        self.day_step = day_step

    def calculate(self, building: Building) -> ExposureResult:
        solar = SolarPosition(building.latitude, building.longitude)

        monthly_totals = [0.0] * 12     # sum of daily hours per month
        monthly_days = [0] * 12         # number of simulated days per month

        annual_hours = 0.0
        weighted_score = 0.0
        peak_daily_hours = 0.0

        start = datetime(self.year, 1, 1, tzinfo=timezone.utc)
        end = datetime(self.year + 1, 1, 1, tzinfo=timezone.utc)
        step_day = timedelta(days=self.day_step)
        step_hour = timedelta(hours=self.hour_step)

        day = start
        while day < end:
            month_idx = day.month - 1
            daily_hours = 0.0
            daily_weighted = 0.0

            t = day
            while t < day + timedelta(days=1):
                pos = solar.position(t)
                if pos["is_daylight"]:
                    angle_to_facade = building.angle_to_sun(pos["azimuth"])
                    if angle_to_facade < 90:
                        # Sun shines on this facade; intensity ~ cos(angle) * sin(elevation)
                        intensity = (
                            math.cos(math.radians(angle_to_facade))
                            * math.sin(math.radians(pos["elevation"]))
                        )
                        daily_hours += self.hour_step
                        daily_weighted += intensity * self.hour_step
                t += step_hour

            monthly_totals[month_idx] += daily_hours
            monthly_days[month_idx] += 1
            annual_hours += daily_hours
            weighted_score += daily_weighted

            if daily_hours > peak_daily_hours:
                peak_daily_hours = daily_hours

            day += step_day

        # Compute monthly averages before scaling so the divisor isn't stale.
        monthly_avg = [
            monthly_totals[i] / max(monthly_days[i], 1) for i in range(12)
        ]

        # Scale up totals to account for skipped days.
        if self.day_step > 1:
            scale = self.day_step
            annual_hours *= scale
            weighted_score *= scale

        peak_month = monthly_avg.index(max(monthly_avg)) + 1

        return ExposureResult(
            building=building,
            annual_hours=annual_hours,
            peak_daily_hours=peak_daily_hours,
            peak_month=peak_month,
            monthly_avg_hours=monthly_avg,
            weighted_score=weighted_score,
        )
