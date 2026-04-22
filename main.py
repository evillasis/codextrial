#!/usr/bin/env python3
"""
Sun Exposure & 3M Film Recommendation CLI

Usage examples:

  # Building facing South in Madrid
  python main.py --lat 40.4168 --lon -3.7038 --facade-azimuth 180 --address "Gran Via 1, Madrid"

  # Street running NE–SW (45°), analyse both sides, in Miami
  python main.py --lat 25.7617 --lon -80.1918 --street-angle 45 --address "Brickell Ave, Miami"

  # Facade facing SW in New York
  python main.py --lat 40.7128 --lon -74.0060 --cardinal SW --address "Broadway, NY"
"""

import argparse
import sys

from sun_exposure import (
    Building,
    ExposureCalculator,
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
        help="Sample every N days (1=every day, 7=weekly, faster). Default: 7",
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

    return p.parse_args()


def main():
    args = parse_args()
    calc = ExposureCalculator(year=args.year, hour_step=1.0, day_step=args.day_step)

    if args.facade_azimuth is not None:
        buildings = [Building(args.lat, args.lon, args.facade_azimuth, args.address)]
    elif args.street_angle is not None:
        buildings = facade_from_street_angle(
            args.lat, args.lon, args.street_angle, args.street_side, args.address
        )
    else:
        buildings = [facade_from_cardinal(args.lat, args.lon, args.cardinal, args.address)]

    for building in buildings:
        result = calc.calculate(building)
        rec = recommend_protection(result)
        print(format_report(result, rec))
        print()


if __name__ == "__main__":
    main()
