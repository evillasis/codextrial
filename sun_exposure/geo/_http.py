"""
Shared HTTP helper for geo lookups.

All requests include a descriptive User-Agent (required by Nominatim ToS)
and a configurable timeout. Errors raise GeoLookupError so callers can
decide whether to warn-and-continue or abort.
"""

import json
import urllib.request
import urllib.parse
from typing import Any

USER_AGENT = "sun-exposure-calculator/1.0 (open-source; https://github.com/evillasis/codextrial)"
DEFAULT_TIMEOUT = 10  # seconds


class GeoLookupError(Exception):
    pass


def http_get_json(url: str, params: dict | None = None, timeout: int = DEFAULT_TIMEOUT) -> Any:
    """GET a URL, parse JSON, return the parsed object."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        raise GeoLookupError(f"HTTP request failed for {url}: {exc}") from exc


def overpass_query(ql: str, timeout: int = 15) -> Any:
    """Run an Overpass QL query and return the parsed JSON response."""
    url = "https://overpass-api.de/api/interpreter"
    data = urllib.parse.urlencode({"data": ql}).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        raise GeoLookupError(f"Overpass query failed: {exc}") from exc
