#!/usr/bin/env python
"""
FaaS function: request_ride

Independent trigger: given a rider + pickup/dropoff, create a new ride request.
Stateless -- all it knows is what's in the state file at invocation time.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from FaaS.state_store import load_state, save_state, new_id, RideSystemError  # noqa: E402


def handler(state: dict, rider_id: str, pickup, dropoff,
            ride_type: str = "standard", promo_code: str = None) -> dict:
    rider = state["riders"].get(rider_id)
    if rider is None:
        raise RideSystemError(f"unknown rider {rider_id}")
    if rider["banned"]:
        return {"status": "REJECTED", "reason": "rider banned"}

    ride_id = new_id("ride")
    ride = {
        "id": ride_id, "rider_id": rider_id, "pickup": list(pickup), "dropoff": list(dropoff),
        "ride_type": ride_type, "status": "REQUESTED", "driver_id": None,
        "distance_km": None, "fare": None, "paid": False, "promo_code": promo_code,
        "cancellation_fee": 0.0, "started_at": None, "completed_at": None,
    }
    state["rides"][ride_id] = ride
    return ride


def _parse_point(s: str):
    x, y = s.split(",")
    return [float(x), float(y)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--rider", required=True)
    parser.add_argument("--pickup", required=True, help="x,y")
    parser.add_argument("--dropoff", required=True, help="x,y")
    parser.add_argument("--ride-type", default="standard")
    parser.add_argument("--promo-code", default=None)
    args = parser.parse_args()

    state = load_state(args.state)
    result = handler(state, args.rider, _parse_point(args.pickup), _parse_point(args.dropoff),
                      args.ride_type, args.promo_code)
    save_state(args.state, state)
    print(json.dumps(result))
