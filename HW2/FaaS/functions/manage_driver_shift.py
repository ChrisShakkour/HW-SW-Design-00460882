#!/usr/bin/env python
"""FaaS function: manage_driver_shift -- clock a driver in or out."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from FaaS.state_store import load_state, save_state, MAX_SHIFT_HOURS, RideSystemError  # noqa: E402


def handler(state: dict, driver_id: str, action: str) -> dict:
    driver = state["drivers"].get(driver_id)
    if driver is None:
        raise RideSystemError(f"unknown driver {driver_id}")

    if action == "clock_in":
        if driver["hours_driven_today"] >= MAX_SHIFT_HOURS:
            return {"status": "REJECTED", "reason": "max daily hours reached"}
        driver["on_shift"] = True
        driver["available"] = state["vehicles"][driver["vehicle_id"]]["status"] == "AVAILABLE"
        driver["shift_started_at"] = time.time()
        return {"status": "ON_SHIFT"}
    elif action == "clock_out":
        if driver["shift_started_at"] is not None:
            driver["hours_driven_today"] += (time.time() - driver["shift_started_at"]) / 3600.0
        driver["on_shift"] = False
        driver["available"] = False
        driver["shift_started_at"] = None
        return {"status": "OFF_SHIFT", "hours_driven_today": round(driver["hours_driven_today"], 3)}
    raise RideSystemError(f"unknown shift action {action}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--driver", required=True)
    parser.add_argument("--action", required=True, choices=["clock_in", "clock_out"])
    args = parser.parse_args()

    state = load_state(args.state)
    result = handler(state, args.driver, args.action)
    save_state(args.state, state)
    print(json.dumps(result))
