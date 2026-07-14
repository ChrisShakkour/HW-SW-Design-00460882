"""
Shared "external state" layer for the FaaS architecture.

In a real deployment this would be a database or object store (DynamoDB, S3,
Redis, ...) reachable by every function instance. Here it is a single JSON
file on disk. Every function is a *separate process* that:

  1. loads the whole state blob from this file,
  2. applies its own pure business logic to it,
  3. writes the whole state blob back.

This is intentionally simple and, importantly, has NO locking. Two functions
racing to write the same ride/driver can clobber each other's update. That is
a genuine architectural property of naive FaaS-over-shared-state (as opposed
to in-process shared memory in the Traditional design) and is discussed in
the report's isolation/consistency section -- it is not an oversight.

The math/formula constants here intentionally mirror Traditional/ride_system.py
(same business rules), but the code is NOT imported from/shared with it: the
two architectures must stand on their own, so the same fare formula is
reimplemented independently on each side.
"""
from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from typing import Optional

BASE_FARE = 2.5
PER_KM = 1.2
PER_MIN = 0.25
AVG_SPEED_KMH = 40.0
CANCELLATION_FEE = 5.0
MAX_SHIFT_HOURS = 12.0
MAINTENANCE_MILEAGE_KM = 500.0


class RideSystemError(Exception):
    pass


def new_state() -> dict:
    return {"riders": {}, "drivers": {}, "vehicles": {}, "rides": {}, "zones": {}}


def load_state(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return new_state()
    return json.loads(p.read_text())


def save_state(path: str, state: dict) -> None:
    Path(path).write_text(json.dumps(state, indent=2))


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def distance_km(a, b) -> float:
    return math.dist(tuple(a), tuple(b))


def compute_fare(distance_km_: float, duration_min: float,
                  surge_multiplier: float = 1.0, promo_code: Optional[str] = None) -> float:
    fare = (BASE_FARE + distance_km_ * PER_KM + duration_min * PER_MIN) * surge_multiplier
    if promo_code == "SAVE10":
        fare *= 0.9
    return round(fare, 2)


# ---- seeding helpers (not graded operations -- just scenario/test setup) ------
def seed_rider(state: dict, name: str, banned: bool = False) -> str:
    rider_id = new_id("rider")
    state["riders"][rider_id] = {"id": rider_id, "name": name, "banned": banned,
                                  "rating": 5.0, "rating_count": 0}
    return rider_id


def seed_driver(state: dict, name: str, location=(0.0, 0.0), vehicle_type="standard") -> str:
    vehicle_id = new_id("veh")
    state["vehicles"][vehicle_id] = {"id": vehicle_id, "vehicle_type": vehicle_type,
                                      "status": "AVAILABLE", "mileage_km": 0.0}
    driver_id = new_id("driver")
    state["drivers"][driver_id] = {
        "id": driver_id, "name": name, "vehicle_id": vehicle_id,
        "location": list(location), "on_shift": False, "available": False,
        "rating": 5.0, "rating_count": 0, "hours_driven_today": 0.0,
        "shift_started_at": None,
    }
    return driver_id
