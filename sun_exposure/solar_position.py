"""
NOAA solar position algorithm.
Accurate to ~0.01° for dates between 1950–2050.
Reference: https://gml.noaa.gov/grad/solcalc/solareqns.PDF
"""

import math
from datetime import datetime, timezone


class SolarPosition:
    """Sun azimuth and elevation for a given location and UTC datetime."""

    def __init__(self, latitude: float, longitude: float):
        if not (-90 <= latitude <= 90):
            raise ValueError(f"Latitude must be in [-90, 90], got {latitude}")
        if not (-180 <= longitude <= 180):
            raise ValueError(f"Longitude must be in [-180, 180], got {longitude}")
        self.latitude = latitude
        self.longitude = longitude

    def position(self, dt: datetime) -> dict:
        """
        Returns {"azimuth": degrees, "elevation": degrees, "is_daylight": bool}.
        Azimuth: 0=N, 90=E, 180=S, 270=W.
        Elevation: 0=horizon, 90=zenith, negative=below horizon.
        dt must be timezone-aware (UTC recommended).
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        lat_r = math.radians(self.latitude)

        # Fractional year in radians
        day_of_year = dt.timetuple().tm_yday
        hour_utc = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
        gamma = 2 * math.pi / 365 * (day_of_year - 1 + (hour_utc - 12) / 24)

        # Equation of time (minutes)
        eqtime = 229.18 * (
            0.000075
            + 0.001868 * math.cos(gamma)
            - 0.032077 * math.sin(gamma)
            - 0.014615 * math.cos(2 * gamma)
            - 0.04089 * math.sin(2 * gamma)
        )

        # Solar declination (radians)
        decl = (
            0.006918
            - 0.399912 * math.cos(gamma)
            + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma)
            + 0.00148 * math.sin(3 * gamma)
        )

        # True solar time (minutes)
        time_offset = eqtime + 4 * self.longitude  # 4 min per degree
        tst = hour_utc * 60 + time_offset

        # Hour angle (degrees; negative = morning, positive = afternoon)
        ha = tst / 4 - 180

        ha_r = math.radians(ha)

        # Solar zenith angle
        cos_zenith = (
            math.sin(lat_r) * math.sin(decl)
            + math.cos(lat_r) * math.cos(decl) * math.cos(ha_r)
        )
        cos_zenith = max(-1.0, min(1.0, cos_zenith))
        zenith_r = math.acos(cos_zenith)
        elevation = 90 - math.degrees(zenith_r)

        # Solar azimuth (from North, clockwise).
        # NOAA formula: cos(Az) = (sin(δ) - sin(φ)·cos(Z)) / (cos(φ)·sin(Z))
        cos_az = (
            math.sin(decl) - math.sin(lat_r) * math.cos(zenith_r)
        ) / (math.cos(lat_r) * math.sin(zenith_r) + 1e-10)
        cos_az = max(-1.0, min(1.0, cos_az))
        azimuth = math.degrees(math.acos(cos_az))
        if ha > 0:  # afternoon: sun is to the west
            azimuth = 360 - azimuth

        return {
            "azimuth": azimuth % 360,
            "elevation": elevation,
            "is_daylight": elevation > 0,
        }
