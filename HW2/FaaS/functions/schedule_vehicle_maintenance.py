#!/usr/bin/env python
"""FaaS function: schedule_vehicle_maintenance -- flag a high-mileage vehicle for service."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from FaaS.state_store import load_state, save_state, new_id, MAINTENANCE_MILEAGE_KM, RideSystemError  # noqa: E402


def handler(state: dict, vehicle_id: str) -> dict:
    vehicle = state["vehicles"].get(vehicle_id)
    if vehicle is None:
        raise RideSystemError(f"unknown vehicle {vehicle_id}")
    if vehicle["mileage_km"] < MAINTENANCE_MILEAGE_KM:
        return {"status": "NOT_DUE", "mileage_km": round(vehicle["mileage_km"], 1)}
    vehicle["status"] = "OUT_OF_SERVICE"
    vehicle["mileage_km"] = 0.0
    return {"status": "OUT_OF_SERVICE", "ticket_id": new_id("maint")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--vehicle", required=True)
    args = parser.parse_args()

    state = load_state(args.state)
    result = handler(state, args.vehicle)
    save_state(args.state, state)
    print(json.dumps(result))
