import pytest

from Traditional.ride_system import RideSystemError


def _setup_basic(system):
    rider = system.add_rider("Alice")
    driver = system.add_driver("Bob", location=(0.0, 0.0))
    system.manage_driver_shift(driver.id, "clock_in")
    return rider, driver


def test_request_ride_happy_path(system):
    rider, _ = _setup_basic(system)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    assert ride["status"] == "REQUESTED"
    assert ride["rider_id"] == rider.id


def test_request_ride_rejects_banned_rider(system):
    rider = system.add_rider("Eve", banned=True)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(1, 1))
    assert ride["status"] == "REJECTED"


def test_request_ride_unknown_rider_raises(system):
    with pytest.raises(RideSystemError):
        system.request_ride("no_such_rider", pickup=(0, 0), dropoff=(1, 1))


def test_match_driver_prefers_closer_driver(system):
    rider = system.add_rider("Alice")
    far = system.add_driver("Far", location=(100, 100))
    near = system.add_driver("Near", location=(0, 0))
    system.manage_driver_shift(far.id, "clock_in")
    system.manage_driver_shift(near.id, "clock_in")

    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(1, 1))
    result = system.match_driver_to_rider(ride["id"])

    assert result["status"] == "MATCHED"
    assert result["driver_id"] == near.id


def test_match_driver_no_driver_available(system):
    rider = system.add_rider("Alice")
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(1, 1))
    result = system.match_driver_to_rider(ride["id"])
    assert result["status"] == "NO_DRIVER_AVAILABLE"


def test_match_driver_wrong_state_raises(system):
    rider, driver = _setup_basic(system)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(1, 1))
    system.match_driver_to_rider(ride["id"])
    with pytest.raises(RideSystemError):
        system.match_driver_to_rider(ride["id"])  # already MATCHED


def test_full_trip_lifecycle_and_fare(system):
    rider, driver = _setup_basic(system)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    system.match_driver_to_rider(ride["id"])
    system.start_trip(ride["id"])
    result = system.complete_trip(ride["id"])

    assert result["status"] == "COMPLETED"
    assert result["distance_km"] == pytest.approx(5.0, rel=1e-3)
    # fare = (2.5 + 5*1.2 + duration_min*0.25) * 1.0
    duration_min = (5.0 / 40.0) * 60.0
    expected_fare = round((2.5 + 5.0 * 1.2 + duration_min * 0.25), 2)
    assert result["fare"] == pytest.approx(expected_fare, rel=1e-3)


def test_complete_trip_wrong_state_raises(system):
    rider, driver = _setup_basic(system)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    with pytest.raises(RideSystemError):
        system.complete_trip(ride["id"])  # still REQUESTED


def test_promo_code_applies_discount(system):
    assert system.calculate_fare(10, 15, 1.0, "SAVE10") == pytest.approx(
        system.calculate_fare(10, 15, 1.0, None) * 0.9, rel=1e-3)


def test_process_surge_pricing_scales_with_shortage(system):
    low = system.process_surge_pricing("zoneA", pending_requests=2, available_drivers=5)
    high = system.process_surge_pricing("zoneB", pending_requests=10, available_drivers=2)
    assert low["surge_multiplier"] == 1.0
    assert high["surge_multiplier"] > 1.0


def test_process_surge_pricing_caps_at_3x(system):
    result = system.process_surge_pricing("zoneC", pending_requests=1000, available_drivers=0)
    assert result["surge_multiplier"] == 3.0


def test_cancellation_fee_when_rider_cancels_after_match(system):
    rider, driver = _setup_basic(system)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(1, 1))
    system.match_driver_to_rider(ride["id"])
    result = system.handle_cancellation(ride["id"], actor="rider")
    assert result["fee"] == 5.0
    # driver should be freed back up
    assert system.drivers[driver.id].available is True


def test_no_cancellation_fee_before_match(system):
    rider, _ = _setup_basic(system)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(1, 1))
    result = system.handle_cancellation(ride["id"], actor="rider")
    assert result["fee"] == 0.0


def test_no_cancellation_fee_when_driver_cancels(system):
    rider, driver = _setup_basic(system)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(1, 1))
    system.match_driver_to_rider(ride["id"])
    result = system.handle_cancellation(ride["id"], actor="driver")
    assert result["fee"] == 0.0


def test_manage_driver_shift_clock_in_out(system):
    driver = system.add_driver("Bob")
    in_result = system.manage_driver_shift(driver.id, "clock_in")
    assert in_result["status"] == "ON_SHIFT"
    out_result = system.manage_driver_shift(driver.id, "clock_out")
    assert out_result["status"] == "OFF_SHIFT"
    assert system.drivers[driver.id].on_shift is False


def test_process_payment_happy_path_and_double_pay_rejected(system):
    rider, driver = _setup_basic(system)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    system.match_driver_to_rider(ride["id"])
    system.start_trip(ride["id"])
    system.complete_trip(ride["id"])

    result = system.process_payment(ride["id"])
    assert result["status"] == "PAID"
    with pytest.raises(RideSystemError):
        system.process_payment(ride["id"])  # already paid


def test_process_payment_before_completion_raises(system):
    rider, driver = _setup_basic(system)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    with pytest.raises(RideSystemError):
        system.process_payment(ride["id"])


def test_rate_and_review_updates_driver_rating(system):
    rider, driver = _setup_basic(system)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    system.match_driver_to_rider(ride["id"])
    system.start_trip(ride["id"])
    system.complete_trip(ride["id"])

    system.rate_and_review(ride["id"], rater="rider", rating=3.0)
    # first-ever rating replaces the default seed rating (5.0, count=0): (5*0 + 3)/1 = 3.0
    assert system.drivers[driver.id].rating == pytest.approx(3.0, rel=1e-3)


def test_rate_and_review_rejects_out_of_range_rating(system):
    rider, driver = _setup_basic(system)
    ride = system.request_ride(rider.id, pickup=(0, 0), dropoff=(3, 4))
    system.match_driver_to_rider(ride["id"])
    system.start_trip(ride["id"])
    system.complete_trip(ride["id"])
    with pytest.raises(RideSystemError):
        system.rate_and_review(ride["id"], rater="rider", rating=9.0)


def test_schedule_vehicle_maintenance_not_due(system):
    driver = system.add_driver("Bob")
    result = system.schedule_vehicle_maintenance(driver.vehicle_id)
    assert result["status"] == "NOT_DUE"


def test_schedule_vehicle_maintenance_triggers_after_mileage_threshold(system):
    rider, driver = _setup_basic(system)
    # drive far enough, repeatedly, to cross the maintenance mileage threshold
    system.vehicles[driver.vehicle_id].mileage_km = 600.0
    result = system.schedule_vehicle_maintenance(driver.vehicle_id)
    assert result["status"] == "OUT_OF_SERVICE"
    assert system.vehicles[driver.vehicle_id].status == "OUT_OF_SERVICE"


def test_track_vehicle_location_updates_position(system):
    driver = system.add_driver("Bob", location=(0, 0))
    result = system.track_vehicle_location(driver.id, (5, 5))
    assert result["location"] == (5.0, 5.0)
    assert system.drivers[driver.id].location == (5.0, 5.0)
