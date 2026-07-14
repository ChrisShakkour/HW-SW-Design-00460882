import sys
from pathlib import Path

import pytest

HW2_ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS_DIR = HW2_ROOT / "FaaS" / "functions"

if str(HW2_ROOT) not in sys.path:
    sys.path.insert(0, str(HW2_ROOT))

from Traditional.ride_system import RideSharingSystem  # noqa: E402
from FaaS import state_store  # noqa: E402


@pytest.fixture
def system() -> RideSharingSystem:
    """A fresh Traditional in-process system for one test."""
    return RideSharingSystem()


@pytest.fixture
def faas_state() -> dict:
    """A fresh in-memory FaaS state blob, for fast direct-handler unit tests."""
    return state_store.new_state()


@pytest.fixture
def faas_state_file(tmp_path) -> str:
    """A fresh on-disk FaaS state file, for real subprocess-isolation tests."""
    path = tmp_path / "state.json"
    state_store.save_state(str(path), state_store.new_state())
    return str(path)
