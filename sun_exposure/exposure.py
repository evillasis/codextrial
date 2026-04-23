"""
Annual sun exposure calculator.

Samples sun position every hour for every day of the year, accumulates
"effective exposure hours" weighted by sun intensity (sin of elevation).
"""

import math
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Optional

_CURRENT_YEAR = datetime.now().year

from .solar_position import SolarPosition
from .building import Building
from .config import load_config


@dataclass
class ExposureResult:
    building: Building
    annual_hours: float          # hours of direct sun on the facade per year
    peak_daily_hours: float      # max direct-sun hours on a single day
    peak_month: int              # month (1–12) with highest average daily exposure
    monthly_avg_hours: list      # [avg daily hours per month], index 0=Jan
    weighted_score: float        # energy-weighted score (accounts for sun intensity)
    # Optional fields — neutral defaults preserve backward compatibility
    raw_weighted_score: float = 0.0     # weighted_score before altitude correction
    altitude_factor: float = 1.0        # 1.0 = no altitude correction
    altitude_m: float = 0.0
    operating_hours: tuple = (0.0, 24.0)
    store_type: str = "medianera"       # "medianera" | "esquinera"
    # Clear-sky irradiance (Meinel DNI model)
    vertical_irradiance_kwh_m2_year: float = 0.0
    vertical_irradiance_kwh_m2_year_operating_hours: float = 0.0

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
        if self.vertical_irradiance_kwh_m2_year > 0:
            line = (
                f"Clear-sky irrad. : {self.vertical_irradiance_kwh_m2_year:.0f} kWh/m²·year"
            )
            oh = self.vertical_irradiance_kwh_m2_year_operating_hours
            if oh > 0 and oh != self.vertical_irradiance_kwh_m2_year:
                line += f"  (op. hours: {oh:.0f} kWh/m²·year)"
            lines.append(line)
        return "\n".join(lines)


def _meinel_vertical_irradiance(elevation_deg: float, angle_to_facade_deg: float) -> float:
    """
    Clear-sky DNI (Meinel model) projected onto a vertical facade (W/m²).

    DNI = 1367 × 0.7^(AM^0.678)  with Kasten-Young air mass.
    Facade component = DNI × cos(elevation) × cos(angle_to_facade).
    """
    el_r = math.radians(elevation_deg)
    am = 1.0 / (math.sin(el_r) + 0.50572 * (elevation_deg + 6.07995) ** (-1.6364))
    dni = 1367.0 * (0.7 ** (am ** 0.678))
    return max(0.0, dni * math.cos(el_r) * math.cos(math.radians(angle_to_facade_deg)))


class ExposureCalculator:
    """
    Computes annual sun exposure for a Building.

    Parameters
    ----------
    year        : calendar year to simulate (affects leap-year and exact sun path)
    hour_step   : sampling interval in hours (1 = hourly, 0.5 = every 30 min)
    day_step    : skip every N-th day to speed up (1 = every day, 7 = weekly)
    """

    def __init__(
        self,
        year: int = _CURRENT_YEAR,
        hour_step: float = 1.0,
        day_step: int = 1,
        config: "dict | None" = None,
    ):
        self.year = year
        self.hour_step = hour_step
        self.day_step = day_step
        self.config = config if config is not None else load_config()

    def _simulate_facade(self, building: Building, store_profile, solar) -> dict:
        """
        Run the hourly/daily accumulation loop for a single facade orientation.
        Returns a dict of raw (pre-altitude-correction) accumulators.
        """
        monthly_totals = [0.0] * 12
        monthly_days = [0] * 12
        annual_hours = 0.0
        weighted_score = 0.0
        peak_daily_hours = 0.0
        irr_full_wh = 0.0   # Wh/m² — all daylight hours, post-obstruction
        irr_oh_wh = 0.0     # Wh/m² — operating hours only

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

                    # Guard 1: obstruction (mountain or nearby building)
                    if store_profile and store_profile.obstructions.is_blocked(
                        pos["azimuth"], pos["elevation"]
                    ):
                        t += step_hour
                        continue

                    angle_to_facade = building.angle_to_sun(pos["azimuth"])
                    if angle_to_facade < 90:
                        el_deg = pos["elevation"]
                        el_r = math.radians(el_deg)
                        intensity = (
                            math.cos(math.radians(angle_to_facade)) * math.sin(el_r)
                        )
                        irr_sample = (
                            _meinel_vertical_irradiance(el_deg, angle_to_facade)
                            * self.hour_step
                        )
                        irr_full_wh += irr_sample

                        # Guard 2: operating hours filter (local solar time)
                        in_oh = True
                        if store_profile and store_profile.operating_hours != (0.0, 24.0):
                            local_h = (
                                t.hour + t.minute / 60.0 + building.longitude / 15.0
                            ) % 24
                            oh_start, oh_end = store_profile.operating_hours
                            in_oh = oh_start <= local_h < oh_end

                        if not in_oh:
                            t += step_hour
                            continue

                        irr_oh_wh += irr_sample

                        # Guard 3: peak-hour weighting (opt-in)
                        weight = 1.0
                        if store_profile and store_profile.apply_peak_weights:
                            local_h = (
                                t.hour + t.minute / 60.0 + building.longitude / 15.0
                            ) % 24
                            for pw_start, pw_end, pw_weight in store_profile.peak_windows:
                                if pw_start <= local_h < pw_end:
                                    weight = pw_weight
                                    break

                        daily_hours += self.hour_step
                        daily_weighted += intensity * weight * self.hour_step

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
            annual_hours *= self.day_step
            weighted_score *= self.day_step
            irr_full_wh *= self.day_step
            irr_oh_wh *= self.day_step

        return {
            "annual_hours": annual_hours,
            "peak_daily_hours": peak_daily_hours,
            "monthly_avg": monthly_avg,
            "weighted_score": weighted_score,
            "irr_full_wh": irr_full_wh,
            "irr_oh_wh": irr_oh_wh,
        }

    def calculate(self, building: Building, store_profile=None) -> ExposureResult:
        """
        Calculate annual sun exposure for a building facade.

        store_profile : StoreProfile | None
            When None (default), runs the baseline calculation with no
            operating-hour filtering, no peak weighting, and no altitude
            correction — identical to the original behaviour.

        For esquineras (store_profile.store_type == "esquinera") with a
        secondary_facade_azimuth set on the Building, both facades are
        simulated and the result is an area-weighted combination:
            score = (primary × primary_area + secondary × secondary_area)
                    / (primary_area + secondary_area)
        """
        solar = SolarPosition(building.latitude, building.longitude)
        primary = self._simulate_facade(building, store_profile, solar)

        store_type = store_profile.store_type if store_profile else "medianera"

        if store_type == "esquinera" and building.secondary_facade_azimuth is not None:
            sec_building = Building(
                building.latitude,
                building.longitude,
                building.secondary_facade_azimuth,
                building.address,
            )
            secondary = self._simulate_facade(sec_building, store_profile, solar)

            p_area = building.primary_glass_area_m2
            s_area = (
                building.secondary_glass_area_m2
                if building.secondary_glass_area_m2 is not None
                else building.primary_glass_area_m2
            )
            total_area = p_area + s_area

            annual_hours = (
                primary["annual_hours"] * p_area + secondary["annual_hours"] * s_area
            ) / total_area
            peak_daily_hours = max(
                primary["peak_daily_hours"], secondary["peak_daily_hours"]
            )
            raw_weighted_score = (
                primary["weighted_score"] * p_area
                + secondary["weighted_score"] * s_area
            ) / total_area
            monthly_avg = [
                (primary["monthly_avg"][i] * p_area + secondary["monthly_avg"][i] * s_area)
                / total_area
                for i in range(12)
            ]
            irr_full_wh = (
                primary["irr_full_wh"] * p_area + secondary["irr_full_wh"] * s_area
            ) / total_area
            irr_oh_wh = (
                primary["irr_oh_wh"] * p_area + secondary["irr_oh_wh"] * s_area
            ) / total_area
        else:
            annual_hours = primary["annual_hours"]
            peak_daily_hours = primary["peak_daily_hours"]
            raw_weighted_score = primary["weighted_score"]
            monthly_avg = primary["monthly_avg"]
            irr_full_wh = primary["irr_full_wh"]
            irr_oh_wh = primary["irr_oh_wh"]

        # Altitude correction: configurable boost per 300 m.
        altitude_m = store_profile.altitude_m if store_profile else 0.0
        boost = self.config["altitude"]["boost_factor_per_300m"]
        altitude_factor = (1.0 + boost) ** (altitude_m / 300.0)
        weighted_score = raw_weighted_score * altitude_factor

        # Apply altitude boost to irradiance and convert Wh → kWh.
        irr_kwh_year = irr_full_wh * altitude_factor / 1000.0
        irr_kwh_year_oh = irr_oh_wh * altitude_factor / 1000.0

        peak_month = monthly_avg.index(max(monthly_avg)) + 1

        return ExposureResult(
            building=building,
            annual_hours=annual_hours,
            peak_daily_hours=peak_daily_hours,
            peak_month=peak_month,
            monthly_avg_hours=monthly_avg,
            weighted_score=weighted_score,
            raw_weighted_score=raw_weighted_score,
            altitude_factor=altitude_factor,
            altitude_m=altitude_m,
            operating_hours=(
                store_profile.operating_hours if store_profile else (0.0, 24.0)
            ),
            store_type=store_type,
            vertical_irradiance_kwh_m2_year=round(irr_kwh_year, 1),
            vertical_irradiance_kwh_m2_year_operating_hours=round(irr_kwh_year_oh, 1),
        )
