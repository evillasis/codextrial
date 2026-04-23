"""
Tests for retail/site enhancement features:
  - ObstructionProfile
  - StoreProfile operating hours
  - Peak-hour weighting
  - Altitude correction
  - Entry / queue zone analysis
  - Backward compatibility
"""

import math
import pytest

from sun_exposure.building import Building, ObstructionProfile, StoreProfile
from sun_exposure.exposure import ExposureCalculator, ExposureResult
from sun_exposure.recommendation import recommend_protection

MADRID = (40.4168, -3.7038)
BOGOTA = (4.711, -74.072)

FAST = dict(year=2025, day_step=14)


def _calc(**kwargs):
    return ExposureCalculator(**{**FAST, **kwargs})


def south_madrid():
    return Building(*MADRID, 180.0, "test")


# ---------------------------------------------------------------------------
# ObstructionProfile
# ---------------------------------------------------------------------------

class TestObstructionProfile:
    def test_blocked_low_sun_in_sector(self):
        obs = ObstructionProfile([(260, 300, 15)])
        assert obs.is_blocked(280, 10)

    def test_not_blocked_high_sun_in_sector(self):
        obs = ObstructionProfile([(260, 300, 15)])
        assert not obs.is_blocked(280, 20)

    def test_not_blocked_sun_outside_sector(self):
        obs = ObstructionProfile([(260, 300, 15)])
        assert not obs.is_blocked(180, 5)

    def test_wraparound_sector(self):
        obs = ObstructionProfile([(350, 10, 20)])   # spans due North
        assert obs.is_blocked(5, 10)               # inside sector
        assert not obs.is_blocked(180, 10)          # outside sector

    def test_empty_profile_never_blocks(self):
        obs = ObstructionProfile()
        assert not obs.is_blocked(180, 30)
        assert not obs.is_blocked(0, 1)


# ---------------------------------------------------------------------------
# Operating hours
# ---------------------------------------------------------------------------

class TestOperatingHours:
    def test_east_facade_score_lower_with_operating_hours(self):
        # East-facing facade gets morning sun; some of it falls before 11 AM,
        # so filtering to 11–21 must reduce the score.
        east = Building(*MADRID, 90.0)
        calc = _calc()
        baseline = calc.calculate(east).weighted_score
        profile = StoreProfile(operating_hours=(11.0, 21.0))
        filtered = calc.calculate(east, profile).weighted_score
        assert filtered < baseline

    def test_full_day_window_matches_no_profile(self):
        b = south_madrid()
        calc = _calc()
        baseline = calc.calculate(b).weighted_score
        profile = StoreProfile(operating_hours=(0.0, 24.0))
        result = calc.calculate(b, profile).weighted_score
        assert abs(result - baseline) < 1e-9

    def test_zero_width_window_gives_zero_hours(self):
        b = south_madrid()
        calc = _calc()
        profile = StoreProfile(operating_hours=(12.0, 12.0))
        result = calc.calculate(b, profile)
        assert result.annual_hours == 0.0
        assert result.weighted_score == 0.0


# ---------------------------------------------------------------------------
# Peak weighting
# ---------------------------------------------------------------------------

class TestPeakWeighting:
    def test_peak_weights_increase_score(self):
        b = south_madrid()
        calc = _calc()
        base = calc.calculate(b).weighted_score
        profile = StoreProfile(apply_peak_weights=True)
        weighted = calc.calculate(b, profile).weighted_score
        assert weighted > base

    def test_peak_weights_disabled_matches_baseline(self):
        b = south_madrid()
        calc = _calc()
        base = calc.calculate(b).weighted_score
        profile = StoreProfile(apply_peak_weights=False)
        result = calc.calculate(b, profile).weighted_score
        assert abs(result - base) < 1e-9

    def test_uniform_weight_two_doubles_score(self):
        b = south_madrid()
        calc = _calc()
        base = calc.calculate(b).weighted_score
        profile = StoreProfile(
            peak_windows=[(0.0, 24.0, 2.0)],
            apply_peak_weights=True,
        )
        result = calc.calculate(b, profile).weighted_score
        assert abs(result - base * 2.0) < 1e-9


# ---------------------------------------------------------------------------
# Altitude correction
# ---------------------------------------------------------------------------

class TestAltitudeCorrection:
    def test_zero_altitude_unchanged(self):
        b = south_madrid()
        calc = _calc()
        base = calc.calculate(b).weighted_score
        profile = StoreProfile(altitude_m=0.0)
        result = calc.calculate(b, profile)
        assert abs(result.weighted_score - base) < 1e-9
        assert result.altitude_factor == pytest.approx(1.0)

    def test_altitude_2000m_increases_score(self):
        b = south_madrid()
        calc = _calc()
        base = calc.calculate(b).raw_weighted_score  # won't exist without profile yet
        profile = StoreProfile(altitude_m=2000.0)
        result = calc.calculate(b, profile)
        expected_factor = 1.04 ** (2000.0 / 300.0)
        assert result.altitude_factor == pytest.approx(expected_factor, rel=0.001)
        assert result.weighted_score == pytest.approx(result.raw_weighted_score * expected_factor, rel=0.001)

    def test_altitude_factor_stored_in_result(self):
        profile = StoreProfile(altitude_m=1500.0)
        result = _calc().calculate(south_madrid(), profile)
        assert result.altitude_m == pytest.approx(1500.0)
        assert result.altitude_factor == pytest.approx(1.04 ** (1500.0 / 300.0), rel=0.001)

    def test_altitude_zero_via_no_profile(self):
        result = _calc().calculate(south_madrid())
        assert result.altitude_m == 0.0
        assert result.altitude_factor == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Entry / queue zone analysis
# ---------------------------------------------------------------------------

class TestEntryQueueZones:
    def test_entry_and_main_facade_different_scores(self):
        calc = _calc()
        profile = StoreProfile(operating_hours=(11.0, 21.0))
        south = Building(*MADRID, 180.0, "main")
        east = Building(*MADRID, 90.0, "entry")
        r_south = calc.calculate(south, profile)
        r_east = calc.calculate(east, profile)
        assert r_south.weighted_score != r_east.weighted_score

    def test_three_zones_all_return_results(self):
        calc = _calc()
        profile = StoreProfile()
        zones = [
            Building(*MADRID, 180.0, "main"),
            Building(*MADRID, 90.0, "entry"),
            Building(*MADRID, 270.0, "queue"),
        ]
        results = [calc.calculate(z, profile) for z in zones]
        assert all(isinstance(r, ExposureResult) for r in results)
        assert all(r.annual_hours >= 0 for r in results)


# ---------------------------------------------------------------------------
# Obstruction integration with exposure calculation
# ---------------------------------------------------------------------------

class TestObstructionInExposure:
    def test_obstruction_reduces_score(self):
        west = Building(*MADRID, 270.0)
        calc = _calc()
        base = calc.calculate(west).weighted_score
        # Block the western sky — relevant for a west-facing facade
        profile = StoreProfile(obstructions=ObstructionProfile([(200, 340, 30)]))
        result = calc.calculate(west, profile).weighted_score
        assert result < base

    def test_irrelevant_obstruction_unchanged(self):
        south = south_madrid()
        calc = _calc()
        base = calc.calculate(south).weighted_score
        # Block due North — irrelevant for south-facing in northern hemisphere
        profile = StoreProfile(obstructions=ObstructionProfile([(340, 20, 45)]))
        result = calc.calculate(south, profile).weighted_score
        assert abs(result - base) < 1e-9


# ---------------------------------------------------------------------------
# Clear-sky kWh irradiance (Meinel model)
# ---------------------------------------------------------------------------

class TestIrradiance:
    def test_south_madrid_irradiance_plausible_range(self):
        # Meinel clear-sky vertical irradiance for Madrid south facade:
        # literature values are roughly 900–1400 kWh/m²·year.
        result = ExposureCalculator(year=2025, day_step=7).calculate(
            Building(*MADRID, 180.0), StoreProfile()
        )
        assert 800 < result.vertical_irradiance_kwh_m2_year < 1600

    def test_south_beats_north_irradiance(self):
        # South facade receives far more irradiance than north in northern hemisphere.
        calc = ExposureCalculator(year=2025, day_step=7)
        r_s = calc.calculate(Building(*MADRID, 180.0), StoreProfile())
        r_n = calc.calculate(Building(*MADRID, 0.0), StoreProfile())
        assert r_s.vertical_irradiance_kwh_m2_year > r_n.vertical_irradiance_kwh_m2_year * 5

    def test_altitude_increases_irradiance(self):
        calc = ExposureCalculator(year=2025, day_step=14)
        r_sea   = calc.calculate(Building(*BOGOTA, 180.0), StoreProfile(altitude_m=0.0))
        r_bogota = calc.calculate(Building(*BOGOTA, 180.0), StoreProfile(altitude_m=2600.0))
        assert r_bogota.vertical_irradiance_kwh_m2_year > r_sea.vertical_irradiance_kwh_m2_year

    def test_operating_hours_irradiance_le_full_year(self):
        result = ExposureCalculator(year=2025, day_step=14).calculate(
            Building(*MADRID, 180.0), StoreProfile(operating_hours=(11.0, 21.0))
        )
        assert result.vertical_irradiance_kwh_m2_year_operating_hours <= result.vertical_irradiance_kwh_m2_year

    def test_full_day_oh_equals_full_irradiance(self):
        result = ExposureCalculator(year=2025, day_step=14).calculate(
            Building(*MADRID, 180.0), StoreProfile(operating_hours=(0.0, 24.0))
        )
        assert result.vertical_irradiance_kwh_m2_year == pytest.approx(
            result.vertical_irradiance_kwh_m2_year_operating_hours, rel=1e-6
        )

    def test_no_profile_irradiance_populated(self):
        result = ExposureCalculator(year=2025, day_step=7).calculate(
            Building(*MADRID, 180.0)
        )
        assert result.vertical_irradiance_kwh_m2_year > 0


# ---------------------------------------------------------------------------
# Esquinera (corner store — two facades)
# ---------------------------------------------------------------------------

class TestEsquinera:
    def test_esquinera_score_between_primary_and_secondary(self):
        # Area-weighted average must be between the two individual scores.
        south = Building(*MADRID, 180.0, primary_glass_area_m2=13.0,
                         secondary_facade_azimuth=270.0, secondary_glass_area_m2=13.0)
        calc = _calc()
        r_south_only = calc.calculate(Building(*MADRID, 180.0), StoreProfile())
        r_west_only  = calc.calculate(Building(*MADRID, 270.0), StoreProfile())
        r_esq = calc.calculate(south, StoreProfile(store_type="esquinera"))
        lo = min(r_south_only.weighted_score, r_west_only.weighted_score)
        hi = max(r_south_only.weighted_score, r_west_only.weighted_score)
        assert lo <= r_esq.weighted_score <= hi

    def test_esquinera_scores_higher_than_west_only(self):
        # S+W area-weighted average exceeds W-only, since S contributes a higher score.
        south_west = Building(*MADRID, 180.0, primary_glass_area_m2=13.0,
                              secondary_facade_azimuth=270.0, secondary_glass_area_m2=13.0)
        calc = _calc()
        r_esq  = calc.calculate(south_west, StoreProfile(store_type="esquinera"))
        r_west = calc.calculate(Building(*MADRID, 270.0), StoreProfile())
        assert r_esq.weighted_score > r_west.weighted_score

    def test_esquinera_area_weighted_formula(self):
        # Verify the exact area-weighted formula.
        calc = _calc()
        p_area, s_area = 13.0, 7.0
        south_east = Building(*MADRID, 180.0, primary_glass_area_m2=p_area,
                              secondary_facade_azimuth=90.0, secondary_glass_area_m2=s_area)
        r_primary   = calc.calculate(Building(*MADRID, 180.0), StoreProfile())
        r_secondary = calc.calculate(Building(*MADRID,  90.0), StoreProfile())
        r_esq = calc.calculate(south_east, StoreProfile(store_type="esquinera"))

        expected = (
            r_primary.raw_weighted_score * p_area
            + r_secondary.raw_weighted_score * s_area
        ) / (p_area + s_area)
        assert r_esq.raw_weighted_score == pytest.approx(expected, rel=0.001)

    def test_medianera_ignores_secondary_azimuth(self):
        # store_type="medianera" must ignore secondary_facade_azimuth.
        south_with_secondary = Building(*MADRID, 180.0, secondary_facade_azimuth=270.0)
        south_plain = Building(*MADRID, 180.0)
        calc = _calc()
        r_med  = calc.calculate(south_with_secondary, StoreProfile(store_type="medianera"))
        r_base = calc.calculate(south_plain, StoreProfile())
        assert r_med.weighted_score == pytest.approx(r_base.weighted_score, rel=1e-9)

    def test_esquinera_no_secondary_azimuth_falls_back_to_primary(self):
        # If secondary_facade_azimuth is None, esquinera behaves like medianera.
        south = Building(*MADRID, 180.0)  # no secondary
        calc = _calc()
        r_esq  = calc.calculate(south, StoreProfile(store_type="esquinera"))
        r_base = calc.calculate(south, StoreProfile())
        assert r_esq.weighted_score == pytest.approx(r_base.weighted_score, rel=1e-9)

    def test_esquinera_result_store_type_field(self):
        south = Building(*MADRID, 180.0, secondary_facade_azimuth=270.0)
        result = _calc().calculate(south, StoreProfile(store_type="esquinera"))
        assert result.store_type == "esquinera"

    def test_medianera_result_store_type_field(self):
        result = _calc().calculate(Building(*MADRID, 180.0), StoreProfile())
        assert result.store_type == "medianera"

    def test_esquinera_default_secondary_area_equals_primary(self):
        # secondary_glass_area_m2=None → treated as equal to primary_glass_area_m2.
        p_area = 10.0
        b_implicit = Building(*MADRID, 180.0, primary_glass_area_m2=p_area,
                              secondary_facade_azimuth=90.0)
        b_explicit = Building(*MADRID, 180.0, primary_glass_area_m2=p_area,
                              secondary_facade_azimuth=90.0, secondary_glass_area_m2=p_area)
        calc = _calc()
        r_implicit = calc.calculate(b_implicit, StoreProfile(store_type="esquinera"))
        r_explicit = calc.calculate(b_explicit, StoreProfile(store_type="esquinera"))
        assert r_implicit.weighted_score == pytest.approx(r_explicit.weighted_score, rel=1e-9)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_no_profile_arg_matches_none_profile(self):
        b = south_madrid()
        calc = _calc()
        r1 = calc.calculate(b)
        r2 = calc.calculate(b, None)
        assert r1.weighted_score == r2.weighted_score
        assert r1.annual_hours == r2.annual_hours

    def test_no_profile_altitude_factor_is_one(self):
        result = _calc().calculate(south_madrid())
        assert result.altitude_factor == 1.0

    def test_no_profile_operating_hours_is_full_day(self):
        result = _calc().calculate(south_madrid())
        assert result.operating_hours == (0.0, 24.0)
