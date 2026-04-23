"""
(latitude, longitude) → ObstructionProfile from nearby OSM buildings.

Queries OSM for building footprints within a radius, estimates each
building's height, computes its blocking elevation angle and azimuth
range as seen from the target point, and returns an ObstructionProfile.

Height estimation priority:
  1. OSM "height" tag (metres, may include " m" suffix)
  2. OSM "building:levels" tag × 3.5 m per floor
  3. Default: 10 m (~3 storeys)
"""

import math
from typing import Optional
from ._http import GeoLookupError, overpass_query
from ..building import ObstructionProfile

DEFAULT_HEIGHT_M = 10.0          # assumed if no OSM height data
MIN_BLOCKING_ANGLE_DEG = 2.0     # ignore obstructions below this elevation angle
MIN_DISTANCE_M = 8.0             # ignore buildings this close (likely the target itself)


def get_building_obstructions(
    lat: float,
    lon: float,
    radius_m: int = 120,
) -> ObstructionProfile:
    """
    Return an ObstructionProfile for buildings visible from (lat, lon).

    radius_m : search radius. 120 m covers immediate neighbours on most
               urban streets without making the Overpass query too heavy.

    Returns an empty ObstructionProfile (no obstructions) if the query
    fails or no buildings are found.
    """
    ql = f"""
[out:json][timeout:15];
(
  way(around:{radius_m},{lat},{lon})["building"];
);
out geom;
"""
    try:
        data = overpass_query(ql)
    except GeoLookupError as exc:
        print(f"  [warning] Could not retrieve nearby buildings: {exc}")
        return ObstructionProfile()

    obstructions = []
    for element in data.get("elements", []):
        if element.get("type") != "way":
            continue
        nodes = element.get("geometry", [])
        if len(nodes) < 3:
            continue

        closest = _closest_distance(lat, lon, nodes)
        if closest < MIN_DISTANCE_M:
            continue  # almost certainly the building the user is standing in

        height = _building_height(element.get("tags", {}))
        block_angle = math.degrees(math.atan2(height, closest))
        if block_angle < MIN_BLOCKING_ANGLE_DEG:
            continue

        az_start, az_end = _azimuth_range(lat, lon, nodes)
        obstructions.append((az_start, az_end, round(block_angle, 1)))

    return ObstructionProfile(obstructions)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _closest_distance(lat: float, lon: float, nodes: list) -> float:
    return min(_distance_m(lat, lon, n["lat"], n["lon"]) for n in nodes)


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(math.radians(lat2))
    x = (
        math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
        - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dlon)
    )
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _azimuth_range(lat: float, lon: float, nodes: list) -> tuple:
    """
    Return (az_start, az_end) covering the angular span of the building
    polygon as seen from (lat, lon).

    Uses the "largest gap" method: find the biggest angular gap between
    consecutive vertices (that's the direction away from the building),
    then the range is everything on the other side.
    """
    azimuths = sorted(_bearing(lat, lon, n["lat"], n["lon"]) for n in nodes)
    n = len(azimuths)
    if n == 0:
        return (0.0, 0.0)

    # Gaps between consecutive azimuths (circular)
    gaps = [
        (azimuths[(i + 1) % n] - azimuths[i]) % 360
        for i in range(n)
    ]
    max_gap_idx = gaps.index(max(gaps))

    az_start = azimuths[(max_gap_idx + 1) % n]
    az_end = azimuths[max_gap_idx]
    return (round(az_start, 1), round(az_end, 1))


def _building_height(tags: dict) -> float:
    raw_height = tags.get("height", "")
    if raw_height:
        try:
            return float(str(raw_height).replace("m", "").replace(" ", ""))
        except ValueError:
            pass

    levels = tags.get("building:levels", "")
    if levels:
        try:
            return float(levels) * 3.5
        except ValueError:
            pass

    return DEFAULT_HEIGHT_M
