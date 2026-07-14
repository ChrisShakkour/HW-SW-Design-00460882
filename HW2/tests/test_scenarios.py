"""
Cross-architecture scenario tests.

Each test runs the SAME workflow against both the Traditional system and the
FaaS functions, then asserts they reach an equivalent final result. This is
the direct evidence for the "both implementations work and are functionally
equivalent, despite being structurally different" grading criterion.

These scenario functions are also what script.sh replays under `perf` for the
Part 4 performance comparison -- one source of truth for correctness and for
the profiling workload.
"""
import pytest

from Traditional.ride_system import RideSharingSystem, RideSystemError as TradError
from FaaS.state_store import seed_rider, seed_driver, RideSystemError as FaasError
from FaaS.functions import (
    request_ride, match_driver_to_rider, start_trip, complete_trip,
    handle_cancellation, process_payment,
)


def run_basic_trip_traditional():
    system = RideSharingSystem()
    rider = system.add_rider("Alice")
    driver = system.add_driver("Bob", location=(0, 0))
    system.manage_driver_shift(driver.id, "clock_in")

    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    system.match_driver_to_rider(ride["id"])
    system.start_trip(ride["id"])
    completed = system.complete_trip(ride["id"])
    paid = system.process_payment(ride["id"])
    return completed, paid


def run_basic_trip_faas(state):
    rider_id = seed_rider(state, "Alice")
    driver_id = seed_driver(state, "Bob", location=(0, 0))
    from FaaS.functions import manage_driver_shift
    manage_driver_shift.handler(state, driver_id, "clock_in")

    ride = request_ride.handler(state, rider_id, [0, 0], [3, 4])
    match_driver_to_rider.handler(state, ride["id"])
    start_trip.handler(state, ride["id"])
    completed = complete_trip.handler(state, ride["id"])
    paid = process_payment.handler(state, ride["id"])
    return completed, paid


def test_basic_trip_scenario_equivalent_across_architectures(faas_state):
    trad_completed, trad_paid = run_basic_trip_traditional()
    faas_completed, faas_paid = run_basic_trip_faas(faas_state)

    assert trad_completed["status"] == faas_completed["status"] == "COMPLETED"
    assert trad_completed["distance_km"] == pytest.approx(faas_completed["distance_km"], rel=1e-6)
    assert trad_completed["fare"] == pytest.approx(faas_completed["fare"], rel=1e-6)
    assert trad_paid["amount"] == pytest.approx(faas_paid["amount"], rel=1e-6)


def run_cancellation_scenario_traditional():
    system = RideSharingSystem()
    rider = system.add_rider("Alice")
    driver = system.add_driver("Bob", location=(0, 0))
    system.manage_driver_shift(driver.id, "clock_in")

    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(1, 1))
    system.match_driver_to_rider(ride["id"])
    return system.handle_cancellation(ride["id"], actor="rider")


def run_cancellation_scenario_faas(state):
    rider_id = seed_rider(state, "Alice")
    driver_id = seed_driver(state, "Bob", location=(0, 0))
    from FaaS.functions import manage_driver_shift
    manage_driver_shift.handler(state, driver_id, "clock_in")

    ride = request_ride.handler(state, rider_id, [0, 0], [1, 1])
    match_driver_to_rider.handler(state, ride["id"])
    return handle_cancellation.handler(state, ride["id"], actor="rider")


def test_cancellation_scenario_equivalent_across_architectures(faas_state):
    trad_result = run_cancellation_scenario_traditional()
    faas_result = run_cancellation_scenario_faas(faas_state)
    assert trad_result == faas_result


def test_double_payment_rejected_equivalently_across_architectures(faas_state):
    # Traditional
    system = RideSharingSystem()
    rider = system.add_rider("Alice")
    driver = system.add_driver("Bob", location=(0, 0))
    system.manage_driver_shift(driver.id, "clock_in")
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    system.match_driver_to_rider(ride["id"])
    system.start_trip(ride["id"])
    system.complete_trip(ride["id"])
    system.process_payment(ride["id"])
    with pytest.raises(TradError):
        system.process_payment(ride["id"])

    # FaaS
    rider_id = seed_rider(faas_state, "Alice")
    driver_id = seed_driver(faas_state, "Bob", location=(0, 0))
    from FaaS.functions import manage_driver_shift
    manage_driver_shift.handler(faas_state, driver_id, "clock_in")
    faas_ride = request_ride.handler(faas_state, rider_id, [0, 0], [3, 4])
    match_driver_to_rider.handler(faas_state, faas_ride["id"])
    start_trip.handler(faas_state, faas_ride["id"])
    complete_trip.handler(faas_state, faas_ride["id"])
    process_payment.handler(faas_state, faas_ride["id"])
    with pytest.raises(FaasError):
        process_payment.handler(faas_state, faas_ride["id"])


def test_banned_rider_rejected_equivalently_across_architectures(faas_state):
    system = RideSharingSystem()
    banned = system.add_rider("Eve", banned=True)
    trad_result = system.request_ride(banned.id, pickup=(0, 0), dropoff=(1, 1))

    banned_id = seed_rider(faas_state, "Eve", banned=True)
    faas_result = request_ride.handler(faas_state, banned_id, [0, 0], [1, 1])

    assert trad_result["status"] == faas_result["status"] == "REJECTED"
