#!/usr/bin/env python
"""
Deterministic workload driver for the FaaS architecture.

Runs the exact same `--num-rides` full trip lifecycles as
Traditional/run_workload.py, but each step is a SEPARATE OS process (a real
`python some_function.py ...` invocation reading/writing a shared state file)
instead of an in-process method call. This is intentional: it is precisely
the process-per-call overhead (process creation, file I/O, no shared memory)
that Part 4's perf comparison is meant to surface.

Same deterministic fleet/pickups/dropoffs as the Traditional driver, so the
printed RESULT line can be diffed against it as a correctness sanity check
before profiling either one.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HW2_ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS_DIR = HW2_ROOT / "FaaS" / "functions"
sys.path.insert(0, str(HW2_ROOT))

from FaaS import state_store  # noqa: E402

NUM_DRIVERS = 5
PICKUPS = [(0, 0), (5, 5), (10, 0), (0, 10), (3, 3)]
DROPOFFS = [(3, 4), (8, 9), (13, 4), (3, 13), (6, 7)]


def call(script: str, state_path: str, *args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(FUNCTIONS_DIR / script), "--state", state_path, *args],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{script} failed: {proc.stderr}")
    return json.loads(proc.stdout)


def run(num_rides: int) -> None:
    state = state_store.new_state()
    driver_ids = [
        state_store.seed_driver(state, f"driver{i}", location=(i * 2.0, i * 2.0))
        for i in range(NUM_DRIVERS)
    ]
    rider_ids = [state_store.seed_rider(state, f"rider{i}") for i in range(num_rides)]

    with tempfile.TemporaryDirectory() as tmp:
        state_path = str(Path(tmp) / "state.json")
        state_store.save_state(state_path, state)

        for driver_id in driver_ids:
            call("manage_driver_shift.py", state_path, "--driver", driver_id, "--action", "clock_in")

        total_fare = 0.0
        completed = 0

        for i, rider_id in enumerate(rider_ids):
            pickup = PICKUPS[i % len(PICKUPS)]
            dropoff = DROPOFFS[i % len(DROPOFFS)]

            ride = call("request_ride.py", state_path, "--rider", rider_id,
                        "--pickup", f"{pickup[0]},{pickup[1]}", "--dropoff", f"{dropoff[0]},{dropoff[1]}")
            if ride["status"] != "REQUESTED":
                continue
            match = call("match_driver_to_rider.py", state_path, "--ride", ride["id"])
            if match["status"] != "MATCHED":
                continue
            call("start_trip.py", state_path, "--ride", ride["id"])
            result = call("complete_trip.py", state_path, "--ride", ride["id"])
            call("process_payment.py", state_path, "--ride", ride["id"])
            call("rate_and_review.py", state_path, "--ride", ride["id"], "--rater", "rider", "--rating", "5.0")

            total_fare += result["fare"]
            completed += 1

        print(f"RESULT completed={completed} total_fare={total_fare:.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-rides", type=int, default=50)
    args = parser.parse_args()
    run(args.num_rides)
