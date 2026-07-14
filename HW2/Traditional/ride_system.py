"""
Traditional architecture: a single monolithic RideSharingSystem object.

All operations are methods on one class that share in-memory state directly
(dicts of riders/drivers/vehicles/rides/zones live on `self` and are mutated
in place). There is no serialization boundary between operations -- a call to
one method can be followed immediately by another that sees its effects,
because they all run in the same process and share the same Python objects.
"""
from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

BASE_FARE = 2.5
PER_KM = 1.2
PER_MIN = 0.25
AVG_SPEED_KMH = 40.0
CANCELLATION_FEE = 5.0
MAX_SHIFT_HOURS = 12.0
MAINTENANCE_MILEAGE_KM = 500.0


class RideSystemError(Exception):
    """Raised for invalid operations/state transitions (e.g. double payment)."""


def _distance_km(a, b) -> float:
    return math.dist(a, b)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class Rider:
    id: str
    name: str
    banned: bool = False
    rating: float = 5.0
    rating_count: int = 0


@dataclass
class Vehicle:
    id: str
    vehicle_type: str = "standard"
    status: str = "AVAILABLE"  # AVAILABLE | OUT_OF_SERVICE
    mileage_km: float = 0.0


@dataclass
class Driver:
    id: str
    name: str
    vehicle_id: str
    location: tuple = (0.0, 0.0)
    on_shift: bool = False
    available: bool = False
    rating: float = 5.0
    rating_count: int = 0
    hours_driven_today: float = 0.0
    shift_started_at: Optional[float] = None


@dataclass
class Zone:
    id: str
    surge_multiplier: float = 1.0


@dataclass
class Ride:
    id: str
    rider_id: str
    pickup: tuple
    dropoff: tuple
    ride_type: str = "standard"
    status: str = "REQUESTED"  # REQUESTED|MATCHED|IN_PROGRESS|COMPLETED|CANCELLED
    driver_id: Optional[str] = None
    distance_km: Optional[float] = None
    fare: Optional[float] = None
    paid: bool = False
    promo_code: Optional[str] = None
    cancellation_fee: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


class RideSharingSystem:
    """Shared, mutable, in-process state for the whole fleet."""

    def __init__(self):
        self.riders: dict[str, Rider] = {}
        self.drivers: dict[str, Driver] = {}
        self.vehicles: dict[str, Vehicle] = {}
        self.rides: dict[str, Ride] = {}
        self.zones: dict[str, Zone] = {}

    # ---- setup helpers (not graded "operations", just test/demo scaffolding) --
    def add_rider(self, name: str, banned: bool = False) -> Rider:
        r = Rider(id=_new_id("rider"), name=name, banned=banned)
        self.riders[r.id] = r
        return r

    def add_driver(self, name: str, location=(0.0, 0.0), vehicle_type="standard") -> Driver:
        v = Vehicle(id=_new_id("veh"), vehicle_type=vehicle_type)
        self.vehicles[v.id] = v
        d = Driver(id=_new_id("driver"), name=name, vehicle_id=v.id, location=location)
        self.drivers[d.id] = d
        return d

    def add_zone(self, zone_id: str) -> Zone:
        z = Zone(id=zone_id)
        self.zones[zone_id] = z
        return z

    # ---- the 12 graded operations --------------------------------------------
    def request_ride(self, rider_id: str, pickup, dropoff, ride_type="standard",
                      promo_code: Optional[str] = None) -> dict:
        rider = self.riders.get(rider_id)
        if rider is None:
            raise RideSystemError(f"unknown rider {rider_id}")
        if rider.banned:
            return {"status": "REJECTED", "reason": "rider banned"}
        ride = Ride(id=_new_id("ride"), rider_id=rider_id, pickup=tuple(pickup),
                    dropoff=tuple(dropoff), ride_type=ride_type, promo_code=promo_code)
        self.rides[ride.id] = ride
        return asdict(ride)

    def match_driver_to_rider(self, ride_id: str, exclude_driver_id: Optional[str] = None) -> dict:
        ride = self._get_ride(ride_id)
        if ride.status != "REQUESTED":
            raise RideSystemError(f"ride {ride_id} not in REQUESTED state")

        candidates = [
            d for d in self.drivers.values()
            if d.available and d.on_shift and d.id != exclude_driver_id
            and self.vehicles[d.vehicle_id].status == "AVAILABLE"
            and self.vehicles[d.vehicle_id].vehicle_type == ride.ride_type
        ]
        if not candidates:
            return {"status": "NO_DRIVER_AVAILABLE"}

        best = min(candidates, key=lambda d: (_distance_km(d.location, ride.pickup), -d.rating))
        best.available = False
        ride.driver_id = best.id
        ride.status = "MATCHED"
        eta_min = (_distance_km(best.location, ride.pickup) / AVG_SPEED_KMH) * 60.0
        return {"status": "MATCHED", "driver_id": best.id, "eta_min": round(eta_min, 2)}

    def track_vehicle_location(self, driver_id: str, location) -> dict:
        driver = self.drivers.get(driver_id)
        if driver is None:
            raise RideSystemError(f"unknown driver {driver_id}")
        driver.location = tuple(location)
        return {"driver_id": driver_id, "location": driver.location}

    def start_trip(self, ride_id: str) -> dict:
        ride = self._get_ride(ride_id)
        if ride.status != "MATCHED":
            raise RideSystemError(f"ride {ride_id} not in MATCHED state")
        ride.status = "IN_PROGRESS"
        ride.started_at = time.time()
        return {"status": "IN_PROGRESS"}

    def complete_trip(self, ride_id: str) -> dict:
        ride = self._get_ride(ride_id)
        if ride.status != "IN_PROGRESS":
            raise RideSystemError(f"ride {ride_id} not in IN_PROGRESS state")

        zone_multiplier = 1.0
        distance = _distance_km(ride.pickup, ride.dropoff)
        duration_min = (distance / AVG_SPEED_KMH) * 60.0
        fare = self.calculate_fare(distance, duration_min, zone_multiplier, ride.promo_code)

        ride.distance_km = round(distance, 3)
        ride.fare = fare
        ride.status = "COMPLETED"
        ride.completed_at = time.time()

        driver = self.drivers.get(ride.driver_id)
        if driver:
            driver.available = True
            self.vehicles[driver.vehicle_id].mileage_km += distance
        return {"status": "COMPLETED", "distance_km": ride.distance_km, "fare": fare}

    def calculate_fare(self, distance_km: float, duration_min: float,
                        surge_multiplier: float = 1.0, promo_code: Optional[str] = None) -> float:
        fare = (BASE_FARE + distance_km * PER_KM + duration_min * PER_MIN) * surge_multiplier
        if promo_code == "SAVE10":
            fare *= 0.9
        return round(fare, 2)

    def process_surge_pricing(self, zone_id: str, pending_requests: int, available_drivers: int) -> dict:
        zone = self.zones.get(zone_id)
        if zone is None:
            zone = self.add_zone(zone_id)
        shortage = max(0, pending_requests - available_drivers)
        zone.surge_multiplier = round(min(3.0, 1.0 + shortage * 0.1), 2)
        return {"zone_id": zone_id, "surge_multiplier": zone.surge_multiplier}

    def handle_cancellation(self, ride_id: str, actor: str) -> dict:
        ride = self._get_ride(ride_id)
        if ride.status not in ("REQUESTED", "MATCHED", "IN_PROGRESS"):
            raise RideSystemError(f"ride {ride_id} cannot be cancelled from {ride.status}")

        fee = CANCELLATION_FEE if actor == "rider" and ride.status in ("MATCHED", "IN_PROGRESS") else 0.0
        ride.cancellation_fee = fee
        ride.status = "CANCELLED"

        if ride.driver_id:
            driver = self.drivers.get(ride.driver_id)
            if driver:
                driver.available = True
        return {"status": "CANCELLED", "fee": fee}

    def manage_driver_shift(self, driver_id: str, action: str) -> dict:
        driver = self.drivers.get(driver_id)
        if driver is None:
            raise RideSystemError(f"unknown driver {driver_id}")

        if action == "clock_in":
            if driver.hours_driven_today >= MAX_SHIFT_HOURS:
                return {"status": "REJECTED", "reason": "max daily hours reached"}
            driver.on_shift = True
            driver.available = self.vehicles[driver.vehicle_id].status == "AVAILABLE"
            driver.shift_started_at = time.time()
            return {"status": "ON_SHIFT"}
        elif action == "clock_out":
            if driver.shift_started_at is not None:
                driver.hours_driven_today += (time.time() - driver.shift_started_at) / 3600.0
            driver.on_shift = False
            driver.available = False
            driver.shift_started_at = None
            return {"status": "OFF_SHIFT", "hours_driven_today": round(driver.hours_driven_today, 3)}
        raise RideSystemError(f"unknown shift action {action}")

    def process_payment(self, ride_id: str) -> dict:
        ride = self._get_ride(ride_id)
        if ride.status != "COMPLETED":
            raise RideSystemError(f"ride {ride_id} not COMPLETED, cannot pay")
        if ride.paid:
            raise RideSystemError(f"ride {ride_id} already paid")
        ride.paid = True
        return {"status": "PAID", "amount": ride.fare}

    def rate_and_review(self, ride_id: str, rater: str, rating: float) -> dict:
        ride = self._get_ride(ride_id)
        if ride.status != "COMPLETED":
            raise RideSystemError(f"ride {ride_id} not COMPLETED, cannot rate")
        if not (1.0 <= rating <= 5.0):
            raise RideSystemError("rating must be between 1 and 5")

        if rater == "rider":  # rider rates the driver
            driver = self.drivers[ride.driver_id]
            driver.rating = round(
                (driver.rating * driver.rating_count + rating) / (driver.rating_count + 1), 2)
            driver.rating_count += 1
        elif rater == "driver":  # driver rates the rider
            r = self.riders[ride.rider_id]
            r.rating = round((r.rating * r.rating_count + rating) / (r.rating_count + 1), 2)
            r.rating_count += 1
        else:
            raise RideSystemError("rater must be 'rider' or 'driver'")
        return {"status": "RATED"}

    def handle_driver_cancellation_with_reassignment(self, ride_id: str) -> dict:
        """
        Part 3 feature extension: when a driver cancels mid-ride, don't just
        leave the rider with a CANCELLED ride -- free the old driver, reopen
        the ride, and immediately re-run matching against the rest of the
        fleet. Trivial here because match_driver_to_rider is just another
        method on this same shared object; no new infrastructure needed.
        """
        ride = self._get_ride(ride_id)
        if ride.status not in ("MATCHED", "IN_PROGRESS"):
            raise RideSystemError(f"ride {ride_id} has no driver to cancel from state {ride.status}")

        old_driver_id = ride.driver_id
        old_driver = self.drivers.get(old_driver_id)
        if old_driver:
            old_driver.available = True
        ride.driver_id = None
        ride.status = "REQUESTED"

        # exclude the driver who just cancelled -- don't immediately hand the
        # same ride right back to them
        match_result = self.match_driver_to_rider(ride_id, exclude_driver_id=old_driver_id)
        if match_result["status"] == "MATCHED":
            return {"status": "REASSIGNED", "new_driver_id": match_result["driver_id"]}
        return {"status": "WAITING_FOR_DRIVER"}

    def schedule_vehicle_maintenance(self, vehicle_id: str) -> dict:
        vehicle = self.vehicles.get(vehicle_id)
        if vehicle is None:
            raise RideSystemError(f"unknown vehicle {vehicle_id}")
        if vehicle.mileage_km < MAINTENANCE_MILEAGE_KM:
            return {"status": "NOT_DUE", "mileage_km": round(vehicle.mileage_km, 1)}
        vehicle.status = "OUT_OF_SERVICE"
        vehicle.mileage_km = 0.0
        return {"status": "OUT_OF_SERVICE", "ticket_id": _new_id("maint")}

    # ---- internals ------------------------------------------------------------
    def _get_ride(self, ride_id: str) -> Ride:
        ride = self.rides.get(ride_id)
        if ride is None:
            raise RideSystemError(f"unknown ride {ride_id}")
        return ride
