#!/usr/bin/env python3
"""
Sun Exposure & 3M Film Recommendation CLI

BASIC USAGE
-----------
  # Explicit coordinates + facade direction
  python main.py --lat 40.4168 --lon -3.7038 --facade-azimuth 180

  # Street: analyse both sides
  python main.py --lat 25.7617 --lon -80.1918 --street-angle 45

  # Cardinal shorthand
  python main.py --lat 40.7128 --lon -74.0060 --cardinal SW

AUTO-DERIVE INPUTS (requires internet)
---------------------------------------
  # Geocode address, derive street angle, altitude & nearby building shadows
  python main.py --address "Gran Via 1, Madrid" --auto

  # Provide coords, auto-derive everything except orientation
  python main.py --lat 40.4168 --lon -3.7038 --auto-street --auto-elevation --auto-buildings

  # Mix: fix the facade direction, still auto-derive altitude + shadows
  python main.py --lat 40.4168 --lon -3.7038 --facade-azimuth 180 --auto-elevation --auto-buildings

RETAIL STORE ANALYSIS
---------------------
  python main.py \\
    --address "Calle 72, Bogotá" --auto \\
    --operating-hours 11,21 --peak-weights \\
    --entry-azimuth 90 --queue-azimuth 270
"""

import argparse
import sys
from datetime import datetime

from sun_exposure import (
    Building,
    ExposureCalculator,
    ObstructionProfile,
    StoreProfile,
    facade_from_street_angle,
    recommend_protection,
)
from sun_exposure.building import facade_from_cardinal
from sun_exposure.recommendation import format_report
from sun_exposure.config import load_config
from sun_exposure.geo import (
    GeoLookupError,
    geocode,
    get_building_obstructions,
    get_elevation,
    get_street_angle,
)


def parse_args():
    p = argparse.ArgumentParser(
        description="Calculate sun exposure and 3M film recommendation for a building facade.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # --- Location ---
    p.add_argument("--lat", type=float, default=None, help="Latitude (decimal degrees)")
    p.add_argument("--lon", type=float, default=None, help="Longitude (decimal degrees)")
    p.add_argument(
        "--address",
        default="",
        help=(
            "Human-readable address. Used as a display label, and as the "
            "geocoding query when --lat/--lon are omitted."
        ),
    )

    # --- Auto-derive inputs ---
    auto = p.add_argument_group("auto-derive inputs (require internet connection)")
    auto.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="Enable all auto-derivation: geocoding + street angle + elevation + buildings",
    )
    auto.add_argument(
        "--auto-street",
        action="store_true",
        default=False,
        help="Derive street bearing from OSM (replaces --street-angle / --facade-azimuth / --cardinal)",
    )
    auto.add_argument(
        "--auto-elevation",
        action="store_true",
        default=False,
        help="Derive altitude from Open-Elevation API (sets --altitude automatically)",
    )
    auto.add_argument(
        "--auto-buildings",
        action="store_true",
        default=False,
        help="Derive nearby building obstructions from OSM (adds to --obstruction list)",
    )

    # --- Facade orientation (one required unless --auto-street/--auto) ---
    orientation = p.add_mutually_exclusive_group(required=False)
    orientation.add_argument(
        "--facade-azimuth",
        type=float,
        help="Outward facade azimuth in degrees (0=N, 90=E, 180=S, 270=W)",
    )
    orientation.add_argument(
        "--street-angle",
        type=float,
        help="Street direction in degrees from North; analyses both facade sides",
    )
    orientation.add_argument(
        "--cardinal",
        type=str,
        help="Cardinal direction the facade faces: N, NE, E, SE, S, SW, W, NW, etc.",
    )
    p.add_argument(
        "--street-side",
        choices=["left", "right", "both"],
        default="both",
        help="Which side of the street to analyse with --street-angle or --auto-street (default: both)",
    )

    # --- Config ---
    p.add_argument(
        "--config",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a custom YAML config file (requires pyyaml). Overrides recommendation thresholds and peak windows.",
    )

    # --- Simulation settings ---
    p.add_argument("--year", type=int, default=datetime.now().year, help="Year to simulate (default: current year)")
    p.add_argument(
        "--day-step",
        type=int,
        default=7,
        help="Sample every N days (1=daily, 7=weekly). Default: 7",
    )

    # --- Retail / site enhancements ---
    site = p.add_argument_group("retail / site context (all optional)")
    site.add_argument(
        "--altitude",
        type=float,
        default=None,
        metavar="METRES",
        help="Site altitude in metres above sea level (overrides --auto-elevation if both given)",
    )
    site.add_argument(
        "--operating-hours",
        type=str,
        default=None,
        metavar="START,END",
        help="Store operating hours in local solar time, e.g. '11,21'",
    )
    site.add_argument(
        "--peak-weights",
        action="store_true",
        default=False,
        help="Weight peak hours: 1–3 PM ×1.5, 6–8 PM ×1.3",
    )
    site.add_argument(
        "--peak-window",
        type=str,
        action="append",
        default=[],
        metavar="START,END,WEIGHT",
        help="Custom peak window (repeatable). Implies --peak-weights.",
    )
    site.add_argument(
        "--obstruction",
        type=str,
        action="append",
        default=[],
        metavar="AZ_START,AZ_END,BLOCK_EL",
        help=(
            "Manual horizon obstruction (repeatable). "
            "E.g. --obstruction 260,300,15  (merged with --auto-buildings if both used)"
        ),
    )
    site.add_argument(
        "--entry-azimuth",
        type=float,
        default=None,
        help="Facade azimuth of the store entry/exit — analysed as a separate zone",
    )
    site.add_argument(
        "--queue-azimuth",
        type=float,
        default=None,
        help="Direction customers face at checkout — analysed as a separate zone",
    )

    return p, p.parse_args()


def _resolve_location(args, parser) -> tuple[float, float]:
    """Return (lat, lon), geocoding --address if coordinates are missing."""
    if args.lat is not None and args.lon is not None:
        return args.lat, args.lon

    if not args.address:
        parser.error(
            "Provide --lat and --lon, or --address (for automatic geocoding)."
        )

    print(f" Geocoding  : '{args.address}' …")
    try:
        result = geocode(args.address)
    except GeoLookupError as exc:
        parser.error(f"Geocoding failed: {exc}")

    print(f"           → {result['display_name']}")
    print(f"           → {result['lat']:.5f}°, {result['lon']:.5f}°")
    return result["lat"], result["lon"]


def _resolve_orientation(args, lat, lon, parser) -> list:
    """Return a list of Building objects based on orientation flags."""
    use_auto_street = args.auto or args.auto_street

    has_explicit = (
        args.facade_azimuth is not None
        or args.street_angle is not None
        or args.cardinal is not None
    )

    if has_explicit and use_auto_street:
        parser.error(
            "--auto-street / --auto conflicts with explicit orientation flags "
            "(--facade-azimuth, --street-angle, --cardinal)."
        )

    if not has_explicit and not use_auto_street:
        parser.error(
            "Specify a facade orientation: --facade-azimuth, --street-angle, "
            "--cardinal, or --auto-street / --auto."
        )

    if args.facade_azimuth is not None:
        return [Building(lat, lon, args.facade_azimuth, args.address)]

    if args.street_angle is not None:
        return facade_from_street_angle(lat, lon, args.street_angle, args.street_side, args.address)

    if args.cardinal is not None:
        return [facade_from_cardinal(lat, lon, args.cardinal, args.address)]

    # Auto-derive street angle from OSM
    print(" Street angle: querying OSM …")
    try:
        angle = get_street_angle(lat, lon)
    except GeoLookupError as exc:
        parser.error(f"Street angle lookup failed: {exc}")

    if angle is None:
        parser.error(
            "No road found near the given location. "
            "Try --facade-azimuth or --street-angle instead."
        )

    print(f"           → street bearing {angle:.1f}°")
    return facade_from_street_angle(lat, lon, angle, args.street_side, args.address)


def main():
    parser, args = parse_args()

    # 1. Resolve coordinates
    lat, lon = _resolve_location(args, parser)

    # 2. Resolve facade orientation → list of Building objects
    buildings = _resolve_orientation(args, lat, lon, parser)

    # 3. Add optional entry / queue zones
    if args.entry_azimuth is not None:
        label = (args.address + " [entry]").strip()
        buildings.append(Building(lat, lon, args.entry_azimuth, label))
    if args.queue_azimuth is not None:
        label = (args.address + " [queue]").strip()
        buildings.append(Building(lat, lon, args.queue_azimuth, label))

    # 4. Auto-derive altitude
    altitude_m = 0.0
    if args.altitude is not None:
        altitude_m = args.altitude
    elif args.auto or args.auto_elevation:
        print(" Elevation  : querying Open-Elevation …")
        altitude_m = get_elevation(lat, lon)
        print(f"           → {altitude_m:.0f} m above sea level")

    # 5. Build obstruction list (manual + auto-buildings merged)
    obs_list = []
    for obs_str in args.obstruction:
        parts = [float(x) for x in obs_str.split(",")]
        obs_list.append((parts[0], parts[1], parts[2]))

    if args.auto or args.auto_buildings:
        print(" Buildings  : querying OSM for nearby obstructions …")
        try:
            osm_obs = get_building_obstructions(lat, lon)
            n = len(osm_obs.obstructions)
            print(f"           → {n} obstruction sector{'s' if n != 1 else ''} found")
            obs_list.extend(osm_obs.obstructions)
        except GeoLookupError as exc:
            print(f"  [warning] Building obstruction lookup failed: {exc}")

    # 6. Parse operating hours and peak windows
    operating_hours = (0.0, 24.0)
    if args.operating_hours:
        parts = [float(x) for x in args.operating_hours.split(",")]
        operating_hours = (parts[0], parts[1])

    custom_peaks = []
    for pw_str in args.peak_window:
        parts = [float(x) for x in pw_str.split(",")]
        custom_peaks.append((parts[0], parts[1], parts[2]))

    # 7. Always build StoreProfile — documented defaults apply when flags are absent
    cfg = load_config(args.config)
    default_peaks = [tuple(w) for w in cfg["peak_windows"]]
    peak_windows = custom_peaks if custom_peaks else default_peaks
    store_profile = StoreProfile(
        altitude_m=altitude_m,
        operating_hours=operating_hours,
        peak_windows=peak_windows,
        apply_peak_weights=args.peak_weights or bool(custom_peaks),
        obstructions=ObstructionProfile(obs_list),
    )

    # 8. Run simulation (cfg already loaded in step 7)
    calc = ExposureCalculator(year=args.year, hour_step=1.0, day_step=args.day_step, config=cfg)

    if args.auto or args.auto_elevation or args.auto_buildings or args.auto_street:
        print()  # blank line before reports

    for building in buildings:
        result = calc.calculate(building, store_profile)
        rec = recommend_protection(result, config=cfg)
        print(format_report(result, rec))
        print()


if __name__ == "__main__":
    main()
