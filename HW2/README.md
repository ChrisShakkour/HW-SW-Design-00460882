# HW2 — Ride-Sharing / Fleet Dispatch: Traditional vs. FaaS

This is the working implementation for HW2 (see [HW2.md](HW2.md) / [HW2.pdf](HW2.pdf)
for the full assignment text). It implements the same ride-sharing / fleet
dispatch system twice — once as a **traditional monolith** and once as a
**Function-as-a-Service** style design — so the two architectures can be
compared on correctness, extensibility, performance, and security.

This README documents what exists today and how to run it. The graded
`report.pdf` (max 6 pages, Parts 3–4's *written* analysis) and `ids.pdf` are
written separately, after the implementation and profiling data below are in
hand — this file is the engineering reference, not the submission itself.

## The chosen system

A ride-sharing / fleet dispatch platform (like a small Uber/Lyft). Rides move
through a lifecycle — `REQUESTED → MATCHED → IN_PROGRESS → COMPLETED` (or
`CANCELLED`) — while drivers, vehicles, and per-zone surge pricing are
maintained alongside it. This scenario was picked over the PDF's own examples
(hospital/hotel/airport/university) because it has many interacting,
stateful resources (drivers, vehicles, zones, rides) with real contention,
which gives Part 3's "how many parts of the system change" question real
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
Traditional design's safe in-process shared memory), noted directly in the
report's system-design description rather than as a bug to fix quietly.

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

Requires Python 3.10+ (only standard library at runtime). `pytest` is only
needed if you run the test suite separately (see below); `script.sh` itself
doesn't install or run it — it assumes `python3`/`perf`/`pip` are already on
the machine, since it's meant to be run standalone on the Linux box used for
Part 4 profiling.

```bash
cd HW2
./script.sh
```

This does everything in one pass:
1. Runs the same deterministic 200-ride workload against `Traditional/run_workload.py` and `FaaS/run_workload.py`, and diffs their output — proving the two architectures are functionally equivalent despite being structurally different.
2. **If `perf` is available** (Linux only — this step exits early with a message on Windows/macOS dev machines): runs `perf stat` (5 repetitions, for a mean instead of one noisy sample) on both workloads.
3. Installs `py-spy` via pip if not already present, then records and renders `flamegraph_traditional.svg` / `flamegraph_faas.svg` (`perf record`'s own call-graph unwinding wasn't reliable under nested virtualization, so `py-spy` samples the CPython interpreter's frame stack directly instead). Everything from steps 2-3 lands in `perf_results/` — that's the directory to copy back off the Linux machine for the report.

Run the test suite separately, whenever you want it (it's independent of `script.sh`):
```bash
python -m pip install pytest
python -m pytest tests/ -v
```

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
  layout" above.
- `Traditional/run_workload.py` and `FaaS/run_workload.py` use the *same*
  deterministic fleet/rider/pickup/dropoff data so their final `RESULT` line
  can be diffed byte-for-byte — this is the main "both implementations work
  and are equivalent" evidence, and it's also the exact workload perf profiles
  for Part 4.

### Part 4 — performance evaluation

Run on a real Linux box (KVM guest) via `./script.sh`: `perf stat` (5 reps,
200-ride workload) for cycles/instructions/context-switches/page-faults/wall
time, plus `py-spy`-generated flamegraphs (`perf record`'s call-graph
unwinding wasn't reliable under nested virtualization, so `py-spy` is used
for the flamegraph step specifically — `perf stat`'s numbers are unaffected).
Headline result: FaaS is ~992x slower in wall time and ~974x more CPU cycles
for identical output, driven by ~1,205 separate interpreter cold starts
(one per operation call) rather than the business logic itself — confirmed
visually in the flamegraphs, where ~61% of FaaS's captured stack frames sit
inside Python's import machinery.

See [doc/part4_performance_evaluation.md](doc/part4_performance_evaluation.md)
for the full write-up (methodology, results table, analysis, flamegraph
findings). Raw data: `perf_results/` (perf stat text output + both SVGs,
gitignored by default since it's regenerated by `script.sh`, but currently
committed so the results are available for the report).

### Report

`doc/report.md` is the full 6-page-limit report covering system design,
Part 3, Part 4, an AI tool usage disclosure, and a conclusion — condensed
from `doc/part3_feature_extension.md` and `doc/part4_performance_evaluation.md`.
Built the same way as HW1's report:

```bash
cd HW2/doc
python ../../HW1/md2docx.py report.md report.docx    # Word version
python doc/render_report_pdf.py report.md report.html "HW2 Report"  # HW2-specific CSS (no header underlines)
# then print report.html to PDF (e.g. headless Chrome --print-to-pdf, or open and print from a browser/Word)
```

`report.pdf` currently renders at **3 pages**, well under the 6-page cap.

**Part 5 (security/maintainability) was dropped from the report.** The
assignment PDF shows that section struck through/highlighted, so we're
treating it as not required rather than writing unrequested content — see
`HW2.md`/`HW2.pdf` for the original formatting. The security-relevant
observations we'd have put there (no locking on the FaaS shared state file,
attack-surface differences, isolation tradeoffs) are still noted inline in
the "Overview & System Design" section above, since they're directly
relevant to describing the FaaS design honestly, just not written up as a
standalone graded section.

## What's still open (not yet in this directory)

- Final packaging into `HW2.zip` with the exact required structure
  (`report.pdf`, `ids.pdf`, `script.sh`, `Traditional/`, `FaaS/`).
