"""
(latitude, longitude) → altitude in metres via Open-Elevation API.

Falls back to Open-Topo-Data (SRTM 90 m) if the primary endpoint fails.
Both are free and require no API key.
"""

from ._http import GeoLookupError, http_get_json

_PRIMARY = "https://api.open-elevation.com/api/v1/lookup"
_FALLBACK = "https://api.opentopodata.org/v1/srtm90m"


def get_elevation(lat: float, lon: float) -> float:
    """
    Return altitude in metres above sea level for the given coordinates.

    Tries Open-Elevation first, then Open-Topo-Data as fallback.
    Returns 0.0 and prints a warning if both fail.
    """
    for fetch in (_from_open_elevation, _from_opentopodata):
        try:
            return fetch(lat, lon)
        except GeoLookupError:
            pass

    print(
        f"  [warning] Could not retrieve elevation for ({lat:.5f}, {lon:.5f}). "
        "Using 0 m. Pass --altitude manually if needed."
    )
    return 0.0


def _from_open_elevation(lat: float, lon: float) -> float:
    data = http_get_json(_PRIMARY, params={"locations": f"{lat},{lon}"}, timeout=8)
    results = data.get("results", [])
    if not results:
        raise GeoLookupError("empty response from Open-Elevation")
    return float(results[0]["elevation"])


def _from_opentopodata(lat: float, lon: float) -> float:
    data = http_get_json(_FALLBACK, params={"locations": f"{lat},{lon}"}, timeout=8)
    results = data.get("results", [])
    if not results:
        raise GeoLookupError("empty response from Open-Topo-Data")
    elev = results[0].get("elevation")
    if elev is None:
        raise GeoLookupError("null elevation from Open-Topo-Data")
    return float(elev)
