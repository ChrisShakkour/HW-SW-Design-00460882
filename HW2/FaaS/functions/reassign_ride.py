#!/usr/bin/env python
"""
FaaS "function": reassign_ride -- Part 3 feature extension.

This is deliberately NOT like the other 12 functions. Every other function in
FaaS/functions/ is independent: it touches only the shared state file and has
zero knowledge of any other function. This one is an ORCHESTRATOR -- it reacts
to a driver cancelling mid-ride and must chain two steps together: (1) free
the old driver and reopen the ride, (2) re-run matching against the rest of
the fleet.

In a real cloud deployment, composing two independently-deployed functions
like this needs a coordinating layer -- a Step Function, an EventBridge rule,
a queue consumer -- something that did not exist before this feature was
requested. Here, that "new piece of infrastructure" is approximated by having
this script invoke match_driver_to_rider.py as its own subprocess, which is
exactly the seam the assignment wants surfaced: FaaS functions are supposed
to have "minimal dependencies between functions", and this feature is the
first one that can't be added without violating that on purpose.

Compare Traditional/ride_system.py's
`handle_driver_cancellation_with_reassignment`: there, step 2 is just calling
`self.match_driver_to_rider(ride_id)` -- no new file, no new process, no new
composition mechanism required.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

FUNCTIONS_DIR = Path(__file__).resolve().parent
HW2_ROOT = FUNCTIONS_DIR.parent.parent
sys.path.insert(0, str(HW2_ROOT))

from FaaS.state_store import load_state, save_state, RideSystemError  # noqa: E402


def _call_function(script: str, state_path: str, *args: str) -> dict:
    """The new seam: invoking another independently-deployable function as a
    separate process, because this orchestrator cannot import its logic
    without violating function independence."""
    proc = subprocess.run(
        [sys.executable, str(FUNCTIONS_DIR / script), "--state", state_path, *args],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{script} failed: {proc.stderr}")
    return json.loads(proc.stdout)


def handler(state_path: str, ride_id: str) -> dict:
    state = load_state(state_path)
    ride = state["rides"].get(ride_id)
    if ride is None:
        raise RideSystemError(f"unknown ride {ride_id}")
    if ride["status"] not in ("MATCHED", "IN_PROGRESS"):
        raise RideSystemError(f"ride {ride_id} has no driver to cancel from state {ride['status']}")

    old_driver_id = ride["driver_id"]
    old_driver = state["drivers"].get(old_driver_id)
    if old_driver:
        old_driver["available"] = True
    ride["driver_id"] = None
    ride["status"] = "REQUESTED"
    save_state(state_path, state)

    # exclude the driver who just cancelled -- don't immediately hand the
    # same ride right back to them
    match_result = _call_function("match_driver_to_rider.py", state_path,
                                   "--ride", ride_id, "--exclude-driver", old_driver_id)
    if match_result["status"] == "MATCHED":
        return {"status": "REASSIGNED", "new_driver_id": match_result["driver_id"]}
    return {"status": "WAITING_FOR_DRIVER"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--ride", required=True)
    args = parser.parse_args()
    result = handler(args.state, args.ride)
    print(json.dumps(result))
