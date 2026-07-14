#!/usr/bin/env python
"""
FaaS function: calculate_fare -- a pre-trip price/estimate quote.

Pure computation: does not read or mutate ride/driver state, only the shared
fare-formula constants. Kept as its own independently-triggerable function
(e.g. an app screen calling it to preview a price before request_ride is ever
called) rather than folded into request_ride or complete_trip.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from FaaS.state_store import load_state, save_state, compute_fare  # noqa: E402


def handler(state: dict, distance_km: float, duration_min: float,
            surge_multiplier: float = 1.0, promo_code: str = None) -> dict:
    fare = compute_fare(distance_km, duration_min, surge_multiplier, promo_code)
    return {"fare": fare}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--distance-km", required=True, type=float)
    parser.add_argument("--duration-min", required=True, type=float)
    parser.add_argument("--surge-multiplier", default=1.0, type=float)
    parser.add_argument("--promo-code", default=None)
    args = parser.parse_args()

    state = load_state(args.state)
    result = handler(state, args.distance_km, args.duration_min, args.surge_multiplier, args.promo_code)
    save_state(args.state, state)  # unchanged, but keeps the CLI contract uniform
    print(json.dumps(result))
