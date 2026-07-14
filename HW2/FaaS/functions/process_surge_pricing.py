#!/usr/bin/env python
"""FaaS function: process_surge_pricing -- recompute a zone's surge multiplier."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from FaaS.state_store import load_state, save_state  # noqa: E402


def handler(state: dict, zone_id: str, pending_requests: int, available_drivers: int) -> dict:
    zone = state["zones"].get(zone_id)
    if zone is None:
        zone = {"id": zone_id, "surge_multiplier": 1.0}
        state["zones"][zone_id] = zone
    shortage = max(0, pending_requests - available_drivers)
    zone["surge_multiplier"] = round(min(3.0, 1.0 + shortage * 0.1), 2)
    return {"zone_id": zone_id, "surge_multiplier": zone["surge_multiplier"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--zone", required=True)
    parser.add_argument("--pending-requests", required=True, type=int)
    parser.add_argument("--available-drivers", required=True, type=int)
    args = parser.parse_args()

    state = load_state(args.state)
    result = handler(state, args.zone, args.pending_requests, args.available_drivers)
    save_state(args.state, state)
    print(json.dumps(result))
