# HW2 — Ride-Sharing / Fleet Dispatch: Traditional vs. FaaS

This is the working implementation for HW2 (see [HW2.md](HW2.md) / [HW2.pdf](HW2.pdf)
for the full assignment text). It implements the same ride-sharing / fleet
dispatch system twice — once as a **traditional monolith** and once as a
**Function-as-a-Service** style design — so the two architectures can be
compared on correctness, extensibility, performance, and security.

This README documents what exists today and how to run it. The graded
`report.pdf` (max 6 pages, Parts 3–5's *written* analysis) and `ids.pdf` are
written separately, after the implementation and profiling data below are in
hand — this file is the engineering reference, not the submission itself.

## The chosen system

A ride-sharing / fleet dispatch platform (like a small Uber/Lyft). Rides move
through a lifecycle — `REQUESTED → MATCHED → IN_PROGRESS → COMPLETED` (or
`CANCELLED`) — while drivers, vehicles, and per-zone surge pricing are
maintained alongside it. This scenario was picked over the PDF's own examples
(hospital/hotel/airport/university) because it has many interacting,
stateful resources (drivers, vehicles, zones, rides) with real contention,
which gives Part 3's "how many parts of the system change" question and
Part 5's security discussion (payment handling, race conditions) real
substance instead of being a CRUD exercise.

### The 12 operations

| # | Operation | What it does |
|---|---|---|
| 1 | `request_ride` | Validates the rider (rejects banned riders), creates a ride in `REQUESTED` state |
| 2 | `match_driver_to_rider` | Finds the closest available, on-shift driver whose vehicle matches the ride type; reserves them |
| 3 | `track_vehicle_location` | Ingests a GPS ping, updating a driver's live position |
| 4 | `start_trip` | Driver confirms pickup; `MATCHED → IN_PROGRESS` |
| 5 | `complete_trip` | Driver marks dropoff; computes final distance/fare; `IN_PROGRESS → COMPLETED` |
| 6 | `calculate_fare` | Pure fare-quote formula (base + per-km + per-min, surge, promo discount) |
| 7 | `process_surge_pricing` | Recomputes a zone's surge multiplier from a demand/supply shortage |
| 8 | `handle_cancellation` | Cancels a ride; charges a fee only if the rider cancels after a driver was matched |
| 9 | `manage_driver_shift` | Clocks a driver in/out; enforces a max-daily-hours cap |
| 10 | `process_payment` | Charges the completed ride's fare exactly once |
| 11 | `rate_and_review` | Post-trip rating, updates a running average for driver or rider |
| 12 | `schedule_vehicle_maintenance` | Flags a vehicle `OUT_OF_SERVICE` once its mileage crosses a threshold |

That's more than the assignment's minimum of 7 — the extra breadth is what
makes Part 3 (feature extension) and Part 4 (profiling a real multi-step
workload) meaningful rather than trivial.

### Part 3 — feature extension: automatic driver reassignment

When a driver cancels mid-ride, both architectures now attempt to find a
replacement driver instead of just cancelling the ride:

- **Traditional:** `RideSharingSystem.handle_driver_cancellation_with_reassignment`
  — one new ~20-line method that simply calls `match_driver_to_rider` again.
- **FaaS:** `FaaS/functions/reassign_ride.py` — a brand-new *orchestrator*
  function, because composing two previously-independent functions
  (`handle_cancellation`-style logic + `match_driver_to_rider`) can't be done
  without either duplicating logic or one function invoking another as a
  subprocess (which is what it does here, and says so in its own docstring).

See [doc/part3_feature_extension.md](doc/part3_feature_extension.md) for the
full design-change comparison (files touched, risk, which architecture is
easier to extend) — this is the write-up that feeds directly into
`report.pdf`'s Part 3 section. Tests: `tests/test_feature_extension.py`.

## The two architectures

### `Traditional/` — monolith
`ride_system.py` defines one `RideSharingSystem` class. All 12 operations are
methods that read and mutate the same in-memory Python objects (`self.riders`,
`self.drivers`, ... dicts of dataclasses) directly. One process, shared
memory, direct method calls — no serialization anywhere between operations.

### `FaaS/` — independent, stateless functions
`FaaS/functions/*.py` — one file per operation. Each has a `handler(state, ...)`
function (pure-ish: takes a state dict, returns a result, mutates the dict it
was given) **and** a standalone CLI entry point (`python request_ride.py
--state state.json --rider ... --pickup ...`). Run as a script, each function
is a genuinely separate OS process that:

1. loads the *entire* shared state from a JSON file (`FaaS/state_store.py`),
2. applies its logic,
3. writes the whole state back.

There is deliberately **no file locking** on that JSON state file — two
functions racing to update it can clobber each other. That's a real
architectural property of naive FaaS-over-shared-storage (vs. the
Traditional design's safe in-process shared memory), and it's a talking
point for the Part 5 security/isolation discussion, not a bug to fix quietly.

The fare formula and other business constants are **reimplemented
independently** in `FaaS/state_store.py` rather than imported from
`Traditional/`, so the two architectures don't secretly share code — only
their externally observable behavior should match.

## Directory layout

```
HW2/
├── Traditional/
│   ├── ride_system.py       # the monolith: RideSharingSystem class, 12 methods
│   └── run_workload.py      # deterministic N-ride workload driver (used by script.sh)
├── FaaS/
│   ├── state_store.py       # shared JSON state I/O + business constants
│   ├── run_workload.py      # same N-ride workload, but each step is a subprocess
│   └── functions/           # one independently-runnable script per operation
├── tests/
│   ├── conftest.py          # pytest fixtures (fresh system / fresh state per test)
│   ├── test_traditional_unit.py
│   ├── test_faas_unit.py    # handler-level unit tests + real subprocess isolation tests
│   ├── test_scenarios.py    # runs the SAME workflow on both architectures, asserts equivalence
│   └── test_feature_extension.py  # Part 3: driver-reassignment feature, both architectures
├── doc/
│   └── part3_feature_extension.md  # Part 3 design-change write-up (feeds into report.pdf)
├── script.sh                # setup + tests + workload + perf, see below
├── HW2.md / HW2.pdf         # assignment instructions
└── README.md                # this file
```

## How to reproduce

Requires Python 3.10+ (only standard library at runtime; `pytest` for tests).

```bash
cd HW2
./script.sh
```

This does everything in one pass:
1. Installs `pytest`.
2. Runs the full test suite (`tests/`) — 47 tests covering both architectures individually plus cross-architecture equivalence scenarios.
3. Runs the same deterministic 200-ride workload against `Traditional/run_workload.py` and `FaaS/run_workload.py`, and diffs their output — proving the two architectures are functionally equivalent despite being structurally different.
4. **If `perf` is available** (Linux only — this step exits early with a message on Windows/macOS dev machines): runs `perf stat` (5 repetitions, for a mean instead of one noisy sample) on both workloads, then **auto-fetches** the [FlameGraph](https://github.com/brendangregg/FlameGraph) scripts (git-clones them into `.flamegraph-tools/` if not already on `PATH`) and records+renders `flamegraph_traditional.svg` / `flamegraph_faas.svg`. Everything from this step lands in `perf_results/` — that's the directory to copy back off the Linux machine for the report.

Override the ride count, repetitions, or interpreter if needed:
```bash
NUM_RIDES=500 REPS=10 PYTHON=python3.12 ./script.sh
```

### Running things individually

```bash
# tests only
python -m pytest tests/ -v

# a single Traditional run
python Traditional/run_workload.py --num-rides 50

# a single FaaS run (spawns a subprocess per operation per ride)
python FaaS/run_workload.py --num-rides 50

# invoke one FaaS function by hand, to see the isolation for yourself
python FaaS/functions/request_ride.py --state /tmp/state.json \
    --rider <rider_id> --pickup 0,0 --dropoff 3,4
```

## Design notes / assumptions worth knowing before reading the report

- **Distance** between two points is straight-line Euclidean distance in an
  abstract 2D coordinate plane (no real road network/routing) — kept simple
  on purpose since the assignment is about architecture, not mapping.
- **Duration** is derived from distance at a fixed average speed (40 km/h),
  used only to compute fare — not a simulated clock.
- The **FaaS state file has no locking**, intentionally — see "Directory
  layout" above. This is expected to come up in the Part 5 discussion.
- `Traditional/run_workload.py` and `FaaS/run_workload.py` use the *same*
  deterministic fleet/rider/pickup/dropoff data so their final `RESULT` line
  can be diffed byte-for-byte — this is the main "both implementations work
  and are equivalent" evidence, and it's also the exact workload perf profiles
  for Part 4.

## What's still open (not yet in this directory)

- **Part 4 — perf numbers + FlameGraphs.** `script.sh` supports this, but
  needs to actually be run on a Linux machine with `perf` (this dev session
  is on Windows) to produce real profiling data for the report.
- **Part 5 — security/maintainability discussion.** Written analysis, not
  code — goes directly into `report.pdf`. (Recall: the assignment PDF shows
  this section struck through/highlighted — still unconfirmed with course
  staff whether it's required.)
- **`report.pdf`** (≤6 pages) and **`ids.pdf`** — not started.
- Final packaging into `HW2.zip` with the exact required structure
  (`report.pdf`, `ids.pdf`, `script.sh`, `Traditional/`, `FaaS/`).
