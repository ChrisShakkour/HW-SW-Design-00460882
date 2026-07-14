#!/usr/bin/env python
"""FaaS function: match_driver_to_rider -- find and reserve the best available driver."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from FaaS.state_store import load_state, save_state, distance_km, AVG_SPEED_KMH, RideSystemError  # noqa: E402


def handler(state: dict, ride_id: str, exclude_driver_id: str = None) -> dict:
    ride = state["rides"].get(ride_id)
    if ride is None:
        raise RideSystemError(f"unknown ride {ride_id}")
    if ride["status"] != "REQUESTED":
        raise RideSystemError(f"ride {ride_id} not in REQUESTED state")

    candidates = [
        d for d in state["drivers"].values()
        if d["available"] and d["on_shift"] and d["id"] != exclude_driver_id
        and state["vehicles"][d["vehicle_id"]]["status"] == "AVAILABLE"
        and state["vehicles"][d["vehicle_id"]]["vehicle_type"] == ride["ride_type"]
    ]
    if not candidates:
        return {"status": "NO_DRIVER_AVAILABLE"}

    best = min(candidates, key=lambda d: (distance_km(d["location"], ride["pickup"]), -d["rating"]))
    best["available"] = False
    ride["driver_id"] = best["id"]
    ride["status"] = "MATCHED"
    eta_min = (distance_km(best["location"], ride["pickup"]) / AVG_SPEED_KMH) * 60.0
    return {"status": "MATCHED", "driver_id": best["id"], "eta_min": round(eta_min, 2)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--ride", required=True)
    parser.add_argument("--exclude-driver", default=None)
    args = parser.parse_args()

    state = load_state(args.state)
    result = handler(state, args.ride, args.exclude_driver)
    save_state(args.state, state)
    print(json.dumps(result))
