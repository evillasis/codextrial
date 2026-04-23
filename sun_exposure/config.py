"""
Configuration loader for the sun exposure calculator.

The canonical defaults live in config.yaml next to this file.
If pyyaml is not installed, the Python DEFAULT_CONFIG dict is used as
a fallback so the package remains stdlib-only for core use.

Custom configs are loaded with:
    cfg = load_config("path/to/my_market.yaml")
and passed to ExposureCalculator(config=cfg) and recommend_protection(result, config=cfg).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

# ── Hardcoded defaults (single source of truth; also written to config.yaml) ──

DEFAULT_CONFIG: dict[str, Any] = {
    "thresholds": {
        "none": 0.5,
        "low": 1.2,
        "moderate": 2.2,
        "high": 3.5,
        # >= high → CRITICAL
    },
    "peak_windows": [
        [13.0, 15.0, 1.5],   # 1–3 PM × 1.5
        [18.0, 20.0, 1.3],   # 6–8 PM × 1.3
    ],
    "altitude": {
        "boost_factor_per_300m": 0.04,   # +4% irradiance per 300 m
    },
    "films": {
        "none":     "No film needed",
        "low":      "No film / decorative tint",
        "moderate": "3M Prestige Series (light)",
        "high":     "3M Prestige Series (medium)",
        "critical": "3M Prestige Series (dark) or Ceramic IR",
    },
}

_BUNDLED_YAML = Path(__file__).parent / "config.yaml"


def load_config(path: "Path | str | None" = None) -> dict[str, Any]:
    """
    Load and return a configuration dict.

    Parameters
    ----------
    path : path to a YAML file, or None.
        None  → use the bundled config.yaml (or DEFAULT_CONFIG if pyyaml absent).
        Path  → load that file; error if it does not exist.

    The returned dict is always a deep-merged overlay on DEFAULT_CONFIG, so
    partial YAML files (only overriding some keys) are safe.
    """
    if path is None:
        yaml_path = _BUNDLED_YAML
        if not yaml_path.exists():
            return copy.deepcopy(DEFAULT_CONFIG)
    else:
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Config file not found: {yaml_path}")

    try:
        import yaml  # optional dependency
        with open(yaml_path) as fh:
            data = yaml.safe_load(fh) or {}
        return _deep_merge(copy.deepcopy(DEFAULT_CONFIG), data)
    except ImportError:
        if path is not None:
            # User explicitly asked for a YAML file — can't oblige
            raise ImportError(
                "pyyaml is required to load a custom config file. "
                "Install it with: pip install pyyaml"
            )
        return copy.deepcopy(DEFAULT_CONFIG)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (in-place on base, returns base)."""
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val
    return base
