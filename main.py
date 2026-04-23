#!/usr/bin/env python3
"""
Sun Exposure & 3M Film Recommendation CLI

Usage examples:

  # Basic: south-facing facade in Madrid
  python main.py --lat 40.4168 --lon -3.7038 --facade-azimuth 180 --address "Gran Via 1, Madrid"

  # Street running NE–SW (45°), analyse both sides, in Miami
  python main.py --lat 25.7617 --lon -80.1918 --street-angle 45 --address "Brickell Ave, Miami"

  # Facade facing SW in New York
  python main.py --lat 40.7128 --lon -74.0060 --cardinal SW --address "Broadway, NY"

  # Retail store: Bogotá at 2600 m, store hours 11–21, peak weighting, mountain to the west,
  # plus separate analysis for entry facade and checkout queue direction
  python main.py \\
    --lat 4.711 --lon -74.072 \\
    --facade-azimuth 180 \\
    --address "Calle 72, Bogotá" \\
    --altitude 2600 \\
    --operating-hours 11,21 \\
    --peak-weights \\
    --obstruction 250,300,20 \\
    --entry-azimuth 90 \\
    --queue-azimuth 270 \\
    --day-step 7
"""

import argparse
import sys

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


def parse_args():
    p = argparse.ArgumentParser(
        description="Calculate sun exposure and 3M film recommendation for a building facade.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--lat", type=float, required=True, help="Latitude (decimal degrees)")
    p.add_argument("--lon", type=float, required=True, help="Longitude (decimal degrees)")
    p.add_argument("--address", default="", help="Human-readable address (label only)")
    p.add_argument("--year", type=int, default=2025, help="Year to simulate (default: 2025)")
    p.add_argument(
        "--day-step",
        type=int,
        default=7,
        help="Sample every N days (1=every day, 7=weekly). Default: 7",
    )

    orientation = p.add_mutually_exclusive_group(required=True)
    orientation.add_argument(
        "--facade-azimuth",
        type=float,
        help="Outward facade azimuth in degrees (0=N, 90=E, 180=S, 270=W)",
    )
    orientation.add_argument(
        "--street-angle",
        type=float,
        help="Street direction in degrees from North. Analyses both facade sides.",
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
        help="Which side of the street to analyse (only with --street-angle). Default: both",
    )

    # --- Retail / site enhancements (all optional) ---
    p.add_argument(
        "--altitude",
        type=float,
        default=0.0,
        metavar="METRES",
        help="Site altitude in metres above sea level (default: 0)",
    )
    p.add_argument(
        "--operating-hours",
        type=str,
        default=None,
        metavar="START,END",
        help="Store operating hours in local solar time, e.g. '11,21' (default: all hours)",
    )
    p.add_argument(
        "--peak-weights",
        action="store_true",
        default=False,
        help="Apply default peak-hour weights: 1–3 PM ×1.5, 6–8 PM ×1.3",
    )
    p.add_argument(
        "--peak-window",
        type=str,
        action="append",
        default=[],
        metavar="START,END,WEIGHT",
        help="Custom peak window (repeatable). E.g. --peak-window 13,15,1.5. Implies --peak-weights.",
    )
    p.add_argument(
        "--obstruction",
        type=str,
        action="append",
        default=[],
        metavar="AZ_START,AZ_END,BLOCK_EL",
        help=(
            "Horizon obstruction in degrees (repeatable). "
            "E.g. --obstruction 260,300,15 blocks sun below 15° between azimuths 260–300°."
        ),
    )
    p.add_argument(
        "--entry-azimuth",
        type=float,
        default=None,
        help="Facade azimuth of the store entry/exit — analysed as a separate zone",
    )
    p.add_argument(
        "--queue-azimuth",
        type=float,
        default=None,
        help="Direction customers face at the checkout queue — analysed as a separate zone",
    )

    return p.parse_args()


def main():
    args = parse_args()
    calc = ExposureCalculator(year=args.year, hour_step=1.0, day_step=args.day_step)

    # Build main facade(s)
    if args.facade_azimuth is not None:
        buildings = [Building(args.lat, args.lon, args.facade_azimuth, args.address)]
    elif args.street_angle is not None:
        buildings = facade_from_street_angle(
            args.lat, args.lon, args.street_angle, args.street_side, args.address
        )
    else:
        buildings = [facade_from_cardinal(args.lat, args.lon, args.cardinal, args.address)]

    # Add optional entry and queue zones
    if args.entry_azimuth is not None:
        label = (args.address + " [entry]").strip()
        buildings.append(Building(args.lat, args.lon, args.entry_azimuth, label))
    if args.queue_azimuth is not None:
        label = (args.address + " [queue]").strip()
        buildings.append(Building(args.lat, args.lon, args.queue_azimuth, label))

    # Build StoreProfile only when at least one retail arg is non-default
    operating_hours = (0.0, 24.0)
    if args.operating_hours:
        parts = [float(x) for x in args.operating_hours.split(",")]
        operating_hours = (parts[0], parts[1])

    obs_list = []
    for obs_str in args.obstruction:
        parts = [float(x) for x in obs_str.split(",")]
        obs_list.append((parts[0], parts[1], parts[2]))

    custom_peaks = []
    for pw_str in args.peak_window:
        parts = [float(x) for x in pw_str.split(",")]
        custom_peaks.append((parts[0], parts[1], parts[2]))

    use_profile = (
        args.altitude != 0.0
        or args.operating_hours is not None
        or obs_list
        or args.peak_weights
        or custom_peaks
        or args.entry_azimuth is not None
        or args.queue_azimuth is not None
    )

    store_profile = None
    if use_profile:
        peak_windows = custom_peaks if custom_peaks else [(13.0, 15.0, 1.5), (18.0, 20.0, 1.3)]
        store_profile = StoreProfile(
            altitude_m=args.altitude,
            operating_hours=operating_hours,
            peak_windows=peak_windows,
            apply_peak_weights=args.peak_weights or bool(custom_peaks),
            obstructions=ObstructionProfile(obs_list),
        )

    for building in buildings:
        result = calc.calculate(building, store_profile)
        rec = recommend_protection(result)
        print(format_report(result, rec))
        print()


if __name__ == "__main__":
    main()
