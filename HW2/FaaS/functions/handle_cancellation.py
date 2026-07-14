#!/usr/bin/env python
"""FaaS function: handle_cancellation -- cancel a ride, applying a fee if applicable."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from FaaS.state_store import load_state, save_state, CANCELLATION_FEE, RideSystemError  # noqa: E402


def handler(state: dict, ride_id: str, actor: str) -> dict:
    ride = state["rides"].get(ride_id)
    if ride is None:
        raise RideSystemError(f"unknown ride {ride_id}")
    if ride["status"] not in ("REQUESTED", "MATCHED", "IN_PROGRESS"):
        raise RideSystemError(f"ride {ride_id} cannot be cancelled from {ride['status']}")

    fee = CANCELLATION_FEE if actor == "rider" and ride["status"] in ("MATCHED", "IN_PROGRESS") else 0.0
    ride["cancellation_fee"] = fee
    ride["status"] = "CANCELLED"

    if ride["driver_id"]:
        driver = state["drivers"].get(ride["driver_id"])
        if driver:
            driver["available"] = True
    return {"status": "CANCELLED", "fee": fee}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--ride", required=True)
    parser.add_argument("--actor", required=True, choices=["rider", "driver"])
    args = parser.parse_args()

    state = load_state(args.state)
    result = handler(state, args.ride, args.actor)
    save_state(args.state, state)
    print(json.dumps(result))
