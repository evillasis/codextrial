"""
Tests for the geo auto-derive modules.

All HTTP calls are mocked so tests run without network access.
"""

import json
import math
from unittest.mock import patch, MagicMock

import pytest

from sun_exposure.geo._http import GeoLookupError
from sun_exposure.geo.geocode import geocode
from sun_exposure.geo.elevation import get_elevation
from sun_exposure.geo.street_angle import get_street_angle, _bearing, _distance_m
from sun_exposure.geo.nearby_buildings import (
    get_building_obstructions,
    _azimuth_range,
    _building_height,
    _closest_distance,
)
from sun_exposure.building import ObstructionProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_urlopen(payload: dict | list):
    """Return a context-manager mock that yields a fake HTTP response."""
    body = json.dumps(payload).encode()
    cm = MagicMock()
    cm.__enter__ = lambda s: MagicMock(read=lambda: body)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

class TestGeocode:
    def test_returns_lat_lon_display(self):
        fake = [{"lat": "40.4168", "lon": "-3.7038", "display_name": "Gran Via, Madrid"}]
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(fake)):
            result = geocode("Gran Via 1, Madrid")
        assert result["lat"] == pytest.approx(40.4168)
        assert result["lon"] == pytest.approx(-3.7038)
        assert "Madrid" in result["display_name"]

    def test_raises_on_empty_result(self):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen([])):
            with pytest.raises(GeoLookupError, match="no results"):
                geocode("zzz_nonexistent_place_xyzxyz")

    def test_raises_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            with pytest.raises(GeoLookupError):
                geocode("anything")


# ---------------------------------------------------------------------------
# Elevation
# ---------------------------------------------------------------------------

class TestElevation:
    def test_open_elevation_primary(self):
        fake = {"results": [{"elevation": 655.0}]}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(fake)):
            assert get_elevation(40.4168, -3.7038) == pytest.approx(655.0)

    def test_fallback_to_opentopodata(self):
        good = {"results": [{"elevation": 2600.0}]}
        call_count = [0]

        def side_effect(req, timeout=10):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("primary failed")
            return _mock_urlopen(good)

        with patch("urllib.request.urlopen", side_effect=side_effect):
            assert get_elevation(4.711, -74.072) == pytest.approx(2600.0)

    def test_returns_zero_on_both_failures(self, capsys):
        with patch("urllib.request.urlopen", side_effect=OSError("no network")):
            result = get_elevation(0.0, 0.0)
        assert result == 0.0
        assert "warning" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Street angle
# ---------------------------------------------------------------------------

class TestStreetAngle:
    def _fake_overpass(self, nodes):
        return {
            "elements": [
                {
                    "type": "way",
                    "tags": {"highway": "primary"},
                    "geometry": nodes,
                }
            ]
        }

    def test_north_south_road_returns_near_zero_or_180(self):
        # Two points running N–S
        nodes = [
            {"lat": 40.416, "lon": -3.7038},
            {"lat": 40.418, "lon": -3.7038},
        ]
        fake = self._fake_overpass(nodes)
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(fake)):
            angle = get_street_angle(40.4168, -3.7038)
        assert angle is not None
        # Bearing is either ~0° (N) or ~180° (S) depending on node order
        assert angle == pytest.approx(0.0, abs=2) or angle == pytest.approx(180.0, abs=2)

    def test_east_west_road_returns_near_90_or_270(self):
        nodes = [
            {"lat": 40.4168, "lon": -3.705},
            {"lat": 40.4168, "lon": -3.702},
        ]
        fake = self._fake_overpass(nodes)
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(fake)):
            angle = get_street_angle(40.4168, -3.7038)
        assert angle is not None
        assert angle == pytest.approx(90.0, abs=2) or angle == pytest.approx(270.0, abs=2)

    def test_no_roads_returns_none(self):
        fake = {"elements": []}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(fake)):
            assert get_street_angle(0.0, 0.0) is None

    def test_network_error_raises(self):
        with patch("urllib.request.urlopen", side_effect=OSError("no net")):
            with pytest.raises(GeoLookupError):
                get_street_angle(40.0, -3.0)


class TestBearingHelper:
    def test_due_north(self):
        b = _bearing(40.0, -3.0, 41.0, -3.0)
        assert b == pytest.approx(0.0, abs=0.5)

    def test_due_east(self):
        b = _bearing(40.0, -3.0, 40.0, -2.0)
        assert b == pytest.approx(90.0, abs=1.0)

    def test_due_south(self):
        b = _bearing(41.0, -3.0, 40.0, -3.0)
        assert b == pytest.approx(180.0, abs=0.5)


# ---------------------------------------------------------------------------
# Nearby buildings
# ---------------------------------------------------------------------------

class TestNearbyBuildings:
    def _fake_building(self, nodes, tags=None):
        return {
            "type": "way",
            "tags": tags or {"building": "yes"},
            "geometry": nodes,
        }

    def test_returns_obstruction_for_nearby_building(self):
        # Building ~20 m to the east, 10 m tall → blocking angle ≈ 26.6°
        nodes = [
            {"lat": 40.4168, "lon": -3.7033},
            {"lat": 40.4169, "lon": -3.7033},
            {"lat": 40.4169, "lon": -3.7031},
            {"lat": 40.4168, "lon": -3.7031},
        ]
        fake = {"elements": [self._fake_building(nodes)]}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(fake)):
            profile = get_building_obstructions(40.4168, -3.7038)
        assert len(profile.obstructions) > 0
        _, _, block_el = profile.obstructions[0]
        assert block_el > 2.0

    def test_ignores_building_that_is_too_close(self):
        # Nodes within 5 m of target — likely the target building itself
        nodes = [
            {"lat": 40.41680, "lon": -3.70381},
            {"lat": 40.41681, "lon": -3.70381},
            {"lat": 40.41681, "lon": -3.70379},
        ]
        fake = {"elements": [self._fake_building(nodes)]}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(fake)):
            profile = get_building_obstructions(40.4168, -3.7038)
        assert len(profile.obstructions) == 0

    def test_returns_empty_on_network_failure(self, capsys):
        with patch("urllib.request.urlopen", side_effect=OSError("no net")):
            profile = get_building_obstructions(40.0, -3.0)
        assert isinstance(profile, ObstructionProfile)
        assert len(profile.obstructions) == 0
        assert "warning" in capsys.readouterr().out

    def test_building_height_from_height_tag(self):
        assert _building_height({"height": "15"}) == pytest.approx(15.0)
        assert _building_height({"height": "12 m"}) == pytest.approx(12.0)

    def test_building_height_from_levels_tag(self):
        assert _building_height({"building:levels": "4"}) == pytest.approx(14.0)

    def test_building_height_default(self):
        assert _building_height({}) == pytest.approx(10.0)

    def test_azimuth_range_simple(self):
        # Building to the east (~90°), spanning a small angle around it
        nodes = [
            {"lat": 40.416, "lon": -3.700},
            {"lat": 40.418, "lon": -3.700},
        ]
        az_start, az_end = _azimuth_range(40.4168, -3.7038, nodes)
        # The range must contain due east (90°) and be reasonably narrow (<60°)
        assert az_start < 90 < az_end
        assert (az_end - az_start) < 60
