"""
Building facade orientation.

A facade is described by its outward-facing azimuth (0=N, 90=E, 180=S, 270=W).
For a building on a street, the facade normal is perpendicular to the street.
A street running N-S has facades facing E (90°) or W (270°).
A street running E-W has facades facing N (0°) or S (180°).
"""

import math
from dataclasses import dataclass
from typing import Optional


CARDINAL = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5,
    "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
}


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
) -> list["Building"]:
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
) -> "Building":
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
