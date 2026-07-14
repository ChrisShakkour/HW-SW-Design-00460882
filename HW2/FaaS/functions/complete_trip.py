#!/usr/bin/env python
"""FaaS function: complete_trip -- driver marks dropoff, fare is finalized."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from FaaS.state_store import load_state, save_state, distance_km, compute_fare, AVG_SPEED_KMH, RideSystemError  # noqa: E402


def handler(state: dict, ride_id: str) -> dict:
    ride = state["rides"].get(ride_id)
    if ride is None:
        raise RideSystemError(f"unknown ride {ride_id}")
    if ride["status"] != "IN_PROGRESS":
        raise RideSystemError(f"ride {ride_id} not in IN_PROGRESS state")

    zone_multiplier = 1.0
    dist = distance_km(ride["pickup"], ride["dropoff"])
    duration_min = (dist / AVG_SPEED_KMH) * 60.0
    fare = compute_fare(dist, duration_min, zone_multiplier, ride["promo_code"])

    ride["distance_km"] = round(dist, 3)
    ride["fare"] = fare
    ride["status"] = "COMPLETED"
    ride["completed_at"] = time.time()

    driver = state["drivers"].get(ride["driver_id"])
    if driver:
        driver["available"] = True
        state["vehicles"][driver["vehicle_id"]]["mileage_km"] += dist
    return {"status": "COMPLETED", "distance_km": ride["distance_km"], "fare": fare}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--ride", required=True)
    args = parser.parse_args()

    state = load_state(args.state)
    result = handler(state, args.ride)
    save_state(args.state, state)
    print(json.dumps(result))
