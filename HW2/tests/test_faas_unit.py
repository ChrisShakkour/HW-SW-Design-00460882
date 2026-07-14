"""
FaaS unit tests, in two layers:

1. Direct-handler tests (fast): import a function's `handler()` and call it
   in-process against an in-memory state dict. Used for quick iteration.
2. Subprocess tests (slow, marked): actually invoke the function as a
   separate `python func.py ...` process reading/writing a real state file
   on disk. These prove the isolation/statelessness claim is real and not
   just an in-process illusion.
"""
import json
import subprocess
import sys

import pytest

from FaaS import state_store
from FaaS.state_store import RideSystemError, seed_rider, seed_driver
from FaaS.functions import (
    request_ride, match_driver_to_rider, track_vehicle_location, start_trip,
    complete_trip, calculate_fare, process_surge_pricing, handle_cancellation,
    manage_driver_shift, process_payment, rate_and_review, schedule_vehicle_maintenance,
)

from conftest import FUNCTIONS_DIR


# ---- direct-handler tests ---------------------------------------------------

def test_request_ride_happy_path(faas_state):
    rider_id = seed_rider(faas_state, "Alice")
    result = request_ride.handler(faas_state, rider_id, [0, 0], [3, 4])
    assert result["status"] == "REQUESTED"


def test_request_ride_rejects_banned_rider(faas_state):
    rider_id = seed_rider(faas_state, "Eve", banned=True)
    result = request_ride.handler(faas_state, rider_id, [0, 0], [1, 1])
    assert result["status"] == "REJECTED"


def test_request_ride_unknown_rider_raises(faas_state):
    with pytest.raises(RideSystemError):
        request_ride.handler(faas_state, "no_such_rider", [0, 0], [1, 1])


def test_match_driver_prefers_closer_driver(faas_state):
    rider_id = seed_rider(faas_state, "Alice")
    far_id = seed_driver(faas_state, "Far", location=(100, 100))
    near_id = seed_driver(faas_state, "Near", location=(0, 0))
    manage_driver_shift.handler(faas_state, far_id, "clock_in")
    manage_driver_shift.handler(faas_state, near_id, "clock_in")

    ride = request_ride.handler(faas_state, rider_id, [0, 0], [1, 1])
    result = match_driver_to_rider.handler(faas_state, ride["id"])

    assert result["status"] == "MATCHED"
    assert result["driver_id"] == near_id


def test_full_trip_lifecycle_and_fare(faas_state):
    rider_id = seed_rider(faas_state, "Alice")
    driver_id = seed_driver(faas_state, "Bob", location=(0, 0))
    manage_driver_shift.handler(faas_state, driver_id, "clock_in")

    ride = request_ride.handler(faas_state, rider_id, [0, 0], [3, 4])
    match_driver_to_rider.handler(faas_state, ride["id"])
    start_trip.handler(faas_state, ride["id"])
    result = complete_trip.handler(faas_state, ride["id"])

    assert result["status"] == "COMPLETED"
    assert result["distance_km"] == pytest.approx(5.0, rel=1e-3)


def test_calculate_fare_is_pure_and_matches_complete_trip_formula(faas_state):
    quote = calculate_fare.handler(faas_state, distance_km=5.0, duration_min=7.5)
    assert quote["fare"] == pytest.approx(2.5 + 5.0 * 1.2 + 7.5 * 0.25, rel=1e-3)


def test_process_surge_pricing_caps_at_3x(faas_state):
    result = process_surge_pricing.handler(faas_state, "zoneC", pending_requests=1000, available_drivers=0)
    assert result["surge_multiplier"] == 3.0


def test_cancellation_fee_when_rider_cancels_after_match(faas_state):
    rider_id = seed_rider(faas_state, "Alice")
    driver_id = seed_driver(faas_state, "Bob")
    manage_driver_shift.handler(faas_state, driver_id, "clock_in")
    ride = request_ride.handler(faas_state, rider_id, [0, 0], [1, 1])
    match_driver_to_rider.handler(faas_state, ride["id"])

    result = handle_cancellation.handler(faas_state, ride["id"], actor="rider")
    assert result["fee"] == 5.0
    assert faas_state["drivers"][driver_id]["available"] is True


def test_process_payment_double_pay_rejected(faas_state):
    rider_id = seed_rider(faas_state, "Alice")
    driver_id = seed_driver(faas_state, "Bob")
    manage_driver_shift.handler(faas_state, driver_id, "clock_in")
    ride = request_ride.handler(faas_state, rider_id, [0, 0], [3, 4])
    match_driver_to_rider.handler(faas_state, ride["id"])
    start_trip.handler(faas_state, ride["id"])
    complete_trip.handler(faas_state, ride["id"])

    assert process_payment.handler(faas_state, ride["id"])["status"] == "PAID"
    with pytest.raises(RideSystemError):
        process_payment.handler(faas_state, ride["id"])


def test_rate_and_review_updates_driver_rating(faas_state):
    rider_id = seed_rider(faas_state, "Alice")
    driver_id = seed_driver(faas_state, "Bob")
    manage_driver_shift.handler(faas_state, driver_id, "clock_in")
    ride = request_ride.handler(faas_state, rider_id, [0, 0], [3, 4])
    match_driver_to_rider.handler(faas_state, ride["id"])
    start_trip.handler(faas_state, ride["id"])
    complete_trip.handler(faas_state, ride["id"])

    rate_and_review.handler(faas_state, ride["id"], rater="rider", rating=3.0)
    assert faas_state["drivers"][driver_id]["rating"] == pytest.approx(3.0, rel=1e-3)


def test_schedule_vehicle_maintenance_triggers_after_mileage_threshold(faas_state):
    driver_id = seed_driver(faas_state, "Bob")
    vehicle_id = faas_state["drivers"][driver_id]["vehicle_id"]
    faas_state["vehicles"][vehicle_id]["mileage_km"] = 600.0
    result = schedule_vehicle_maintenance.handler(faas_state, vehicle_id)
    assert result["status"] == "OUT_OF_SERVICE"


def test_track_vehicle_location_updates_position(faas_state):
    driver_id = seed_driver(faas_state, "Bob", location=(0, 0))
    result = track_vehicle_location.handler(faas_state, driver_id, [5, 5])
    assert result["location"] == [5, 5]


# ---- real subprocess (true isolation) tests --------------------------------

def _run_cli(script_name: str, *args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(FUNCTIONS_DIR / script_name), *args],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"{script_name} failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_request_ride_runs_as_isolated_process(faas_state_file):
    state = state_store.load_state(faas_state_file)
    rider_id = seed_rider(state, "Alice")
    state_store.save_state(faas_state_file, state)

    result = _run_cli("request_ride.py", "--state", faas_state_file,
                       "--rider", rider_id, "--pickup", "0,0", "--dropoff", "3,4")
    assert result["status"] == "REQUESTED"

    # the ride must now be visible in the state file to the NEXT process
    persisted = state_store.load_state(faas_state_file)
    assert result["id"] in persisted["rides"]


def test_full_trip_lifecycle_across_separate_processes(faas_state_file):
    state = state_store.load_state(faas_state_file)
    rider_id = seed_rider(state, "Alice")
    driver_id = seed_driver(state, "Bob", location=(0, 0))
    state_store.save_state(faas_state_file, state)

    _run_cli("manage_driver_shift.py", "--state", faas_state_file,
              "--driver", driver_id, "--action", "clock_in")
    ride = _run_cli("request_ride.py", "--state", faas_state_file,
                     "--rider", rider_id, "--pickup", "0,0", "--dropoff", "3,4")
    match = _run_cli("match_driver_to_rider.py", "--state", faas_state_file, "--ride", ride["id"])
    assert match["status"] == "MATCHED"

    _run_cli("start_trip.py", "--state", faas_state_file, "--ride", ride["id"])
    complete = _run_cli("complete_trip.py", "--state", faas_state_file, "--ride", ride["id"])
    assert complete["status"] == "COMPLETED"

    payment = _run_cli("process_payment.py", "--state", faas_state_file, "--ride", ride["id"])
    assert payment["status"] == "PAID"
    assert payment["amount"] == complete["fare"]
