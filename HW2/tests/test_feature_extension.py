"""
Part 3 feature extension: automatic driver reassignment when a driver cancels
mid-ride, instead of stranding the rider with a CANCELLED ride.

These tests exercise both implementations and, in the last test, run the same
scenario on each to show they reach an equivalent outcome despite the FaaS
side needing a new orchestrator (reassign_ride.py) that the Traditional side
didn't need at all (a plain method on the existing class).
"""
import json
import subprocess
import sys

import pytest

from Traditional.ride_system import RideSharingSystem, RideSystemError as TradError
from FaaS import state_store
from FaaS.state_store import seed_rider, seed_driver, RideSystemError as FaasError
from FaaS.functions import request_ride, match_driver_to_rider, manage_driver_shift

from conftest import FUNCTIONS_DIR


# ---- Traditional: trivial, one method on the existing class ----------------

def test_traditional_reassignment_finds_replacement_driver():
    system = RideSharingSystem()
    rider = system.add_rider("Alice")
    d1 = system.add_driver("Bob", location=(0, 0))
    d2 = system.add_driver("Carl", location=(1, 1))
    system.manage_driver_shift(d1.id, "clock_in")
    system.manage_driver_shift(d2.id, "clock_in")

    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    system.match_driver_to_rider(ride["id"])  # should grab d1 (closer)
    assert system.rides[ride["id"]].driver_id == d1.id

    result = system.handle_driver_cancellation_with_reassignment(ride["id"])
    assert result["status"] == "REASSIGNED"
    assert result["new_driver_id"] == d2.id
    assert system.drivers[d1.id].available is True  # old driver freed


def test_traditional_reassignment_no_driver_available():
    system = RideSharingSystem()
    rider = system.add_rider("Alice")
    driver = system.add_driver("Bob", location=(0, 0))
    system.manage_driver_shift(driver.id, "clock_in")

    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    system.match_driver_to_rider(ride["id"])

    result = system.handle_driver_cancellation_with_reassignment(ride["id"])
    assert result["status"] == "WAITING_FOR_DRIVER"
    assert system.rides[ride["id"]].status == "REQUESTED"


def test_traditional_reassignment_wrong_state_raises():
    system = RideSharingSystem()
    rider = system.add_rider("Alice")
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    with pytest.raises(TradError):
        system.handle_driver_cancellation_with_reassignment(ride["id"])  # still REQUESTED, no driver to cancel


# ---- FaaS: needs a new orchestrator that shells out to another function ----

def _run_reassign_cli(state_path: str, ride_id: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(FUNCTIONS_DIR / "reassign_ride.py"),
         "--state", state_path, "--ride", ride_id],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_faas_reassignment_finds_replacement_driver(faas_state_file):
    state = state_store.load_state(faas_state_file)
    rider_id = seed_rider(state, "Alice")
    d1 = seed_driver(state, "Bob", location=(0, 0))
    d2 = seed_driver(state, "Carl", location=(1, 1))
    manage_driver_shift.handler(state, d1, "clock_in")
    manage_driver_shift.handler(state, d2, "clock_in")
    ride = request_ride.handler(state, rider_id, [0, 0], [3, 4])
    match_driver_to_rider.handler(state, ride["id"])
    assert state["rides"][ride["id"]]["driver_id"] == d1
    state_store.save_state(faas_state_file, state)

    result = _run_reassign_cli(faas_state_file, ride["id"])
    assert result["status"] == "REASSIGNED"
    assert result["new_driver_id"] == d2

    final_state = state_store.load_state(faas_state_file)
    assert final_state["drivers"][d1]["available"] is True


def test_faas_reassignment_no_driver_available(faas_state_file):
    state = state_store.load_state(faas_state_file)
    rider_id = seed_rider(state, "Alice")
    driver_id = seed_driver(state, "Bob", location=(0, 0))
    manage_driver_shift.handler(state, driver_id, "clock_in")
    ride = request_ride.handler(state, rider_id, [0, 0], [3, 4])
    match_driver_to_rider.handler(state, ride["id"])
    state_store.save_state(faas_state_file, state)

    result = _run_reassign_cli(faas_state_file, ride["id"])
    assert result["status"] == "WAITING_FOR_DRIVER"


def test_faas_reassignment_wrong_state_raises(faas_state_file):
    state = state_store.load_state(faas_state_file)
    rider_id = seed_rider(state, "Alice")
    request_ride.handler(state, rider_id, [0, 0], [3, 4])
    state_store.save_state(faas_state_file, state)

    proc = subprocess.run(
        [sys.executable, str(FUNCTIONS_DIR / "reassign_ride.py"),
         "--state", faas_state_file, "--ride", list(state["rides"].keys())[0]],
        capture_output=True, text=True,
    )
    assert proc.returncode != 0  # RideSystemError propagated as a traceback + non-zero exit


# ---- cross-architecture equivalence for this feature specifically ---------

def test_reassignment_equivalent_across_architectures(faas_state_file):
    # Traditional
    system = RideSharingSystem()
    rider = system.add_rider("Alice")
    d1 = system.add_driver("Bob", location=(0, 0))
    d2 = system.add_driver("Carl", location=(1, 1))
    system.manage_driver_shift(d1.id, "clock_in")
    system.manage_driver_shift(d2.id, "clock_in")
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    system.match_driver_to_rider(ride["id"])
    trad_result = system.handle_driver_cancellation_with_reassignment(ride["id"])

    # FaaS
    state = state_store.load_state(faas_state_file)
    rider_id = seed_rider(state, "Alice")
    f1 = seed_driver(state, "Bob", location=(0, 0))
    f2 = seed_driver(state, "Carl", location=(1, 1))
    manage_driver_shift.handler(state, f1, "clock_in")
    manage_driver_shift.handler(state, f2, "clock_in")
    faas_ride = request_ride.handler(state, rider_id, [0, 0], [3, 4])
    match_driver_to_rider.handler(state, faas_ride["id"])
    state_store.save_state(faas_state_file, state)
    faas_result = _run_reassign_cli(faas_state_file, faas_ride["id"])

    assert trad_result["status"] == faas_result["status"] == "REASSIGNED"
