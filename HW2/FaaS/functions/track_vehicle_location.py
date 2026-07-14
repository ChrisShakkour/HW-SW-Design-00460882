#!/usr/bin/env python
"""FaaS function: track_vehicle_location -- ingest a GPS ping for a driver."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from FaaS.state_store import load_state, save_state, RideSystemError  # noqa: E402


def handler(state: dict, driver_id: str, location) -> dict:
    driver = state["drivers"].get(driver_id)
    if driver is None:
        raise RideSystemError(f"unknown driver {driver_id}")
    driver["location"] = list(location)
    return {"driver_id": driver_id, "location": driver["location"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--driver", required=True)
    parser.add_argument("--location", required=True, help="x,y")
    args = parser.parse_args()

    x, y = args.location.split(",")
    state = load_state(args.state)
    result = handler(state, args.driver, [float(x), float(y)])
    save_state(args.state, state)
    print(json.dumps(result))
