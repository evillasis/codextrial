"""
Tests for the solar position and exposure modules.
Run with: python -m pytest tests/ -v
"""

import math
from datetime import datetime, timezone

from sun_exposure.solar_position import SolarPosition
from sun_exposure.building import Building, facade_from_street_angle, facade_from_cardinal
from sun_exposure.exposure import ExposureCalculator
from sun_exposure.recommendation import recommend_protection


class TestSolarPosition:
    def test_solar_noon_is_due_south_northern_hemisphere(self):
        """At solar noon in the Northern Hemisphere (winter), sun is due south."""
        madrid = SolarPosition(40.4168, -3.7038)
        # Jan 1, ~11:30 UTC ≈ solar noon at Madrid longitude in winter
        noon = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        pos = madrid.position(noon)
        assert pos["is_daylight"]
        assert 160 < pos["azimuth"] < 200, f"Expected ~180°, got {pos['azimuth']:.1f}°"
        assert pos["elevation"] > 0

    def test_midnight_is_below_horizon(self):
        london = SolarPosition(51.5074, -0.1278)
        midnight = datetime(2025, 6, 21, 1, 0, tzinfo=timezone.utc)
        pos = london.position(midnight)
        assert not pos["is_daylight"]

    def test_summer_solstice_elevation_madrid(self):
        """Max solar elevation at Madrid on summer solstice ≈ 72°."""
        madrid = SolarPosition(40.4168, -3.7038)
        # ~11:00 UTC ≈ solar noon at Madrid in summer
        noon = datetime(2025, 6, 21, 11, 0, tzinfo=timezone.utc)
        pos = madrid.position(noon)
        assert 65 < pos["elevation"] < 80, f"Expected ~72°, got {pos['elevation']:.1f}°"

    def test_azimuth_morning_is_east_of_south(self):
        """Morning sun should be east of south (azimuth < 180°)."""
        madrid = SolarPosition(40.4168, -3.7038)
        morning = datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc)
        pos = madrid.position(morning)
        if pos["is_daylight"]:
            assert pos["azimuth"] < 180, f"Morning azimuth should be < 180°, got {pos['azimuth']:.1f}°"

    def test_azimuth_afternoon_is_west_of_south(self):
        """Afternoon sun should be west of south (azimuth > 180°)."""
        madrid = SolarPosition(40.4168, -3.7038)
        afternoon = datetime(2025, 1, 1, 15, 0, tzinfo=timezone.utc)
        pos = madrid.position(afternoon)
        assert pos["is_daylight"]
        assert pos["azimuth"] > 180, f"Afternoon azimuth should be > 180°, got {pos['azimuth']:.1f}°"

    def test_invalid_latitude_raises(self):
        import pytest
        with pytest.raises(ValueError):
            SolarPosition(91.0, 0.0)


class TestBuilding:
    def test_facade_from_street_angle_both_sides(self):
        buildings = facade_from_street_angle(40.0, -3.0, 0, "both")
        azimuths = {b.facade_azimuth for b in buildings}
        assert azimuths == {90.0, 270.0}  # N-S street → E and W facades

    def test_facade_from_cardinal(self):
        b = facade_from_cardinal(40.0, -3.0, "SW")
        assert b.facade_azimuth == 225.0
        assert b.cardinal_direction == "SW"

    def test_angle_to_sun_facing_sun(self):
        b = Building(40.0, -3.0, 180.0)  # south-facing
        assert b.angle_to_sun(180.0) == 0.0  # sun due south

    def test_angle_to_sun_90_degrees(self):
        b = Building(40.0, -3.0, 180.0)
        assert b.angle_to_sun(90.0) == 90.0   # sun due east, 90° off facade


class TestExposure:
    def test_south_beats_north_in_madrid(self):
        """South-facing facade must get significantly more sun than north-facing."""
        calc = ExposureCalculator(year=2025, day_step=14)
        south = Building(40.4168, -3.7038, 180.0)
        north = Building(40.4168, -3.7038, 0.0)
        r_south = calc.calculate(south)
        r_north = calc.calculate(north)
        assert r_south.annual_hours > r_north.annual_hours * 3

    def test_south_facade_peak_month_is_equinox(self):
        """South-facing facade peaks near equinox (Mar or Sep)."""
        calc = ExposureCalculator(year=2025, day_step=14)
        south = Building(40.4168, -3.7038, 180.0)
        result = calc.calculate(south)
        # March = 3, September = 9 (equinoxes)
        assert result.peak_month in (2, 3, 9, 10), (
            f"Expected peak near equinox, got month {result.peak_month}"
        )


class TestRecommendation:
    def test_south_facing_madrid_recommends_protection(self):
        calc = ExposureCalculator(year=2025, day_step=14)
        south = Building(40.4168, -3.7038, 180.0, "Test")
        result = calc.calculate(south)
        rec = recommend_protection(result)
        assert rec.protect, "South-facing Madrid facade should recommend protection"

    def test_north_facing_madrid_no_protection(self):
        calc = ExposureCalculator(year=2025, day_step=14)
        north = Building(40.4168, -3.7038, 0.0, "Test")
        result = calc.calculate(north)
        rec = recommend_protection(result)
        assert not rec.protect, "North-facing Madrid facade should not need protection"
