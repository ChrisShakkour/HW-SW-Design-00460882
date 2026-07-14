#!/usr/bin/env python
"""FaaS function: process_payment -- charge the rider for a completed ride."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from FaaS.state_store import load_state, save_state, RideSystemError  # noqa: E402


def handler(state: dict, ride_id: str) -> dict:
    ride = state["rides"].get(ride_id)
    if ride is None:
        raise RideSystemError(f"unknown ride {ride_id}")
    if ride["status"] != "COMPLETED":
        raise RideSystemError(f"ride {ride_id} not COMPLETED, cannot pay")
    if ride["paid"]:
        raise RideSystemError(f"ride {ride_id} already paid")
    ride["paid"] = True
    return {"status": "PAID", "amount": ride["fare"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--ride", required=True)
    args = parser.parse_args()

    state = load_state(args.state)
    result = handler(state, args.ride)
    save_state(args.state, state)
    print(json.dumps(result))
