"""
Building facade orientation.

A facade is described by its outward-facing azimuth (0=N, 90=E, 180=S, 270=W).
For a building on a street, the facade normal is perpendicular to the street.
A street running N-S has facades facing E (90°) or W (270°).
A street running E-W has facades facing N (0°) or S (180°).
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


CARDINAL = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5,
    "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
}


@dataclass
class ObstructionProfile:
    """
    Simplified horizon model for a site (mountains, neighbouring buildings, etc.).

    Each obstruction entry is (azimuth_start, azimuth_end, blocking_elevation_angle):
      - azimuth_start/end: compass degrees (0–360, clockwise from N)
      - blocking_elevation_angle: sun at or below this elevation is blocked in this sector

    Supports wrap-around sectors: azimuth_start=350, azimuth_end=10 covers due North.

    Examples
    --------
    Mountain to the west blocking sun below 20°:
        ObstructionProfile([(250, 300, 20)])

    Tall building to the NE blocking sun below 35°:
        ObstructionProfile([(30, 60, 35)])
    """

    obstructions: List[Tuple[float, float, float]] = field(default_factory=list)

    def is_blocked(self, sun_azimuth: float, sun_elevation: float) -> bool:
        """Return True if the sun is hidden behind an obstruction at this site."""
        for az_start, az_end, block_el in self.obstructions:
            if az_start <= az_end:
                in_sector = az_start <= sun_azimuth <= az_end
            else:                           # wrap-around e.g. 350–10
                in_sector = sun_azimuth >= az_start or sun_azimuth <= az_end
            if in_sector and sun_elevation <= block_el:
                return True
        return False


@dataclass
class StoreProfile:
    """
    Retail-specific site properties for a sun exposure analysis.

    All fields have neutral defaults that reproduce the baseline behaviour
    (no filtering, no weighting, no altitude correction, no obstructions).

    Parameters
    ----------
    altitude_m        : metres above sea level; raises UV/irradiance ~4% per 300 m
    operating_hours   : (start_h, end_h) in local solar time; default (0, 24) = all hours
    peak_windows      : list of (start_h, end_h, weight) — higher weight during busy periods
    apply_peak_weights: must be True to activate peak_windows; default False (opt-in)
    obstructions      : horizon profile for mountains or nearby buildings
    """

    altitude_m: float = 0.0
    operating_hours: Tuple[float, float] = (0.0, 24.0)
    peak_windows: List[Tuple[float, float, float]] = field(
        default_factory=lambda: [(13.0, 15.0, 1.5), (18.0, 20.0, 1.3)]
    )
    apply_peak_weights: bool = False
    obstructions: ObstructionProfile = field(default_factory=ObstructionProfile)


@dataclass
class Building:
    """
    A building facade with a known GPS location and outward-facing direction.

    facade_azimuth: degrees clockwise from North (0–360).
    address: human-readable label for display.
    """

    latitude: float
    longitude: float
    facade_azimuth: float  # outward normal of the window-bearing wall
    address: str = ""

    def __post_init__(self):
        self.facade_azimuth = self.facade_azimuth % 360

    @property
    def cardinal_direction(self) -> str:
        """Closest 16-point compass label for the facade orientation."""
        dirs = list(CARDINAL.keys())
        angles = list(CARDINAL.values())
        diff = [abs((self.facade_azimuth - a + 180) % 360 - 180) for a in angles]
        return dirs[diff.index(min(diff))]

    def angle_to_sun(self, sun_azimuth: float) -> float:
        """
        Angle between the facade normal and the sun direction (0–180°).
        < 90° means sun is shining on this facade.
        """
        diff = abs(self.facade_azimuth - sun_azimuth)
        return min(diff, 360 - diff)


def facade_from_street_angle(
    latitude: float,
    longitude: float,
    street_angle: float,
    side: str = "both",
    address: str = "",
) -> list:
    """
    Given a street running at `street_angle` degrees from North, return one or
    two Building objects representing the facades on each side of the street.

    side: "left" | "right" | "both"
      - "right": facade faces perpendicular-right of the street direction
      - "left": facade faces perpendicular-left of the street direction

    Example: street_angle=0 (N–S street) → right facade faces E (90°), left faces W (270°).
    """
    right_normal = (street_angle + 90) % 360
    left_normal = (street_angle - 90) % 360

    results = []
    if side in ("right", "both"):
        results.append(Building(latitude, longitude, right_normal, address))
    if side in ("left", "both"):
        results.append(Building(latitude, longitude, left_normal, address))
    return results


def facade_from_cardinal(
    latitude: float,
    longitude: float,
    direction: str,
    address: str = "",
) -> Building:
    """
    Create a Building whose facade faces the given cardinal direction string.
    E.g. direction="SW" → facade_azimuth=225°.
    """
    direction = direction.upper().strip()
    if direction not in CARDINAL:
        raise ValueError(
            f"Unknown direction '{direction}'. Valid: {list(CARDINAL.keys())}"
        )
    return Building(latitude, longitude, CARDINAL[direction], address)
