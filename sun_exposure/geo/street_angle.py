"""
(latitude, longitude) → street bearing in degrees from North.

Queries the OSM Overpass API for the nearest road segment and returns
its compass bearing (0–360°). The caller can then pass this to
facade_from_street_angle() to get both facade orientations.
"""

import math
from typing import Optional
from ._http import GeoLookupError, overpass_query


def get_street_angle(lat: float, lon: float, radius_m: int = 60) -> Optional[float]:
    """
    Return the compass bearing of the nearest OSM road to (lat, lon).

    Returns None if no road is found within radius_m metres.

    The bearing is the direction the street runs (0=N, 90=E, …).
    Facade normals are perpendicular: use facade_from_street_angle().
    """
    ql = f"""
[out:json][timeout:12];
way(around:{radius_m},{lat},{lon})["highway"];
out geom;
"""
    data = overpass_query(ql)
    ways = [e for e in data.get("elements", []) if e.get("type") == "way"]

    if not ways:
        return None

    # Find the nearest road segment (closest node to the query point)
    best_bearing: Optional[float] = None
    best_dist = float("inf")

    for way in ways:
        nodes = way.get("geometry", [])
        if len(nodes) < 2:
            continue

        for i in range(len(nodes) - 1):
            n1, n2 = nodes[i], nodes[i + 1]
            mid_lat = (n1["lat"] + n2["lat"]) / 2
            mid_lon = (n1["lon"] + n2["lon"]) / 2
            d = _distance_m(lat, lon, mid_lat, mid_lon)
            if d < best_dist:
                best_dist = d
                best_bearing = _bearing(n1["lat"], n1["lon"], n2["lat"], n2["lon"])

    return best_bearing


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Forward azimuth (degrees, 0=N clockwise) from point 1 to point 2."""
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(math.radians(lat2))
    x = (
        math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
        - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dlon)
    )
    return (math.degrees(math.atan2(y, x)) + 360) % 360
