#!/usr/bin/env python
"""FaaS function: rate_and_review -- post-trip rating from rider or driver."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from FaaS.state_store import load_state, save_state, RideSystemError  # noqa: E402


def handler(state: dict, ride_id: str, rater: str, rating: float) -> dict:
    ride = state["rides"].get(ride_id)
    if ride is None:
        raise RideSystemError(f"unknown ride {ride_id}")
    if ride["status"] != "COMPLETED":
        raise RideSystemError(f"ride {ride_id} not COMPLETED, cannot rate")
    if not (1.0 <= rating <= 5.0):
        raise RideSystemError("rating must be between 1 and 5")

    if rater == "rider":  # rider rates the driver
        driver = state["drivers"][ride["driver_id"]]
        driver["rating"] = round(
            (driver["rating"] * driver["rating_count"] + rating) / (driver["rating_count"] + 1), 2)
        driver["rating_count"] += 1
    elif rater == "driver":  # driver rates the rider
        rider = state["riders"][ride["rider_id"]]
        rider["rating"] = round(
            (rider["rating"] * rider["rating_count"] + rating) / (rider["rating_count"] + 1), 2)
        rider["rating_count"] += 1
    else:
        raise RideSystemError("rater must be 'rider' or 'driver'")
    return {"status": "RATED"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--ride", required=True)
    parser.add_argument("--rater", required=True, choices=["rider", "driver"])
    parser.add_argument("--rating", required=True, type=float)
    args = parser.parse_args()

    state = load_state(args.state)
    result = handler(state, args.ride, args.rater, args.rating)
    save_state(args.state, state)
    print(json.dumps(result))
