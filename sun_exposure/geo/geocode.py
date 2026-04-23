"""
Address → (latitude, longitude) via Nominatim (OpenStreetMap).

Nominatim terms of service:
  - Max 1 request per second
  - Provide a valid User-Agent identifying the app
  - Do not use for bulk geocoding
"""

from typing import Optional
from ._http import GeoLookupError, http_get_json

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def geocode(address: str) -> dict:
    """
    Resolve a free-text address to GPS coordinates.

    Returns
    -------
    dict with keys:
      lat (float), lon (float), display_name (str)

    Raises
    ------
    GeoLookupError  if the request fails or no result is found.
    """
    data = http_get_json(
        NOMINATIM_URL,
        params={"q": address, "format": "json", "limit": 1},
    )

    if not data:
        raise GeoLookupError(
            f"Nominatim returned no results for '{address}'. "
            "Try a more specific address or add the city/country."
        )

    best = data[0]
    return {
        "lat": float(best["lat"]),
        "lon": float(best["lon"]),
        "display_name": best.get("display_name", address),
    }
