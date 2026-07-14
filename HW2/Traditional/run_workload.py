#!/usr/bin/env python
"""
Deterministic workload driver for the Traditional architecture.

Runs `--num-rides` full trip lifecycles (request -> match -> start -> complete
-> pay -> rate) against a small fixed fleet, entirely in one process. This is
the exact workload perf/script.sh profiles, and its printed RESULT line is
also used as a cheap correctness cross-check against FaaS/run_workload.py
(same deterministic inputs must yield the same total fare).
"""
import argparse

from ride_system import RideSharingSystem

NUM_DRIVERS = 5
PICKUPS = [(0, 0), (5, 5), (10, 0), (0, 10), (3, 3)]
DROPOFFS = [(3, 4), (8, 9), (13, 4), (3, 13), (6, 7)]


def build_system(num_drivers=NUM_DRIVERS) -> RideSharingSystem:
    system = RideSharingSystem()
    for i in range(num_drivers):
        driver = system.add_driver(f"driver{i}", location=(i * 2.0, i * 2.0))
        system.manage_driver_shift(driver.id, "clock_in")
    return system


def run(num_rides: int) -> None:
    system = build_system()
    total_fare = 0.0
    completed = 0

    for i in range(num_rides):
        rider = system.add_rider(f"rider{i}")
        pickup = PICKUPS[i % len(PICKUPS)]
        dropoff = DROPOFFS[i % len(DROPOFFS)]

        ride = system.request_ride(rider.id, pickup, dropoff)
        if ride["status"] != "REQUESTED":
            continue
        match = system.match_driver_to_rider(ride["id"])
        if match["status"] != "MATCHED":
            continue
        system.start_trip(ride["id"])
        result = system.complete_trip(ride["id"])
        system.process_payment(ride["id"])
        system.rate_and_review(ride["id"], rater="rider", rating=5.0)

        total_fare += result["fare"]
        completed += 1

    print(f"RESULT completed={completed} total_fare={total_fare:.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-rides", type=int, default=50)
    args = parser.parse_args()
    run(args.num_rides)
