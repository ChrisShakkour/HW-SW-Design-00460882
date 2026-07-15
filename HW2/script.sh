#!/usr/bin/env bash
# =============================================================================
# script.sh -- run the shared deterministic workload against both
# architectures, verify they agree, then profile both with perf + FlameGraphs
# (Part 4). Run from anywhere; it cds to its own dir. Assumes python3/perf/git
# are already installed on this machine. Safe to run without perf (Part 4
# exits early with a message).
#
# Override knobs:
#   PYTHON=python3.12 NUM_RIDES=200 REPS=5 ./script.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
NUM_RIDES=${NUM_RIDES:-200}   # rides fed to both the correctness diff AND the perf stat workload
REPS=${REPS:-5}               # perf stat repetitions, for mean +/- stddev instead of one noisy sample

# FlameGraph recording needs the process to run long enough for a 999Hz sampler
# to catch samples before it exits. Traditional finishes 200 rides in ~0.1s --
# far too fast -- so it gets a much larger ride count just for this step. FaaS
# is already slow per-ride (subprocess-per-call), so it gets a much smaller one.
FG_RIDES_TRADITIONAL=${FG_RIDES_TRADITIONAL:-20000}
FG_RIDES_FAAS=${FG_RIDES_FAAS:-50}

# ---- Shared deterministic workload: same fleet/rides fed to both -----------
echo "=== Running deterministic workload: Traditional ($NUM_RIDES rides) ==="
"$PYTHON" Traditional/run_workload.py --num-rides "$NUM_RIDES" | tee out_traditional.txt

echo
echo "=== Running deterministic workload: FaaS ($NUM_RIDES rides) ==="
"$PYTHON" FaaS/run_workload.py --num-rides "$NUM_RIDES" | tee out_faas.txt

echo
echo "=== Verifying both architectures produced identical results ==="
if diff -q out_traditional.txt out_faas.txt > /dev/null; then
    echo "OK: Traditional and FaaS results are identical"
else
    echo "MISMATCH between architectures:"
    diff out_traditional.txt out_faas.txt || true
    exit 1
fi

# ---- Part 4: profiling -------------------------------------------------------
echo
if ! command -v perf > /dev/null 2>&1; then
    echo "perf not found on this system -- skipping Part 4 profiling."
    echo "Run this script on a Linux machine with perf installed to collect profiling data for the report."
    echo
    echo "=== Done ==="
    exit 0
fi

RESULTS_DIR="perf_results"
mkdir -p "$RESULTS_DIR"

PERF_EVENTS="cycles,instructions,context-switches,page-faults,cpu-clock"

echo "=== perf stat: Traditional ($REPS reps) ==="
rm -f "$RESULTS_DIR/perf_stat_traditional.txt"
perf stat -r "$REPS" -e "$PERF_EVENTS" -o "$RESULTS_DIR/perf_stat_traditional.txt" \
    "$PYTHON" Traditional/run_workload.py --num-rides "$NUM_RIDES" > /dev/null
cat "$RESULTS_DIR/perf_stat_traditional.txt"

echo
echo "=== perf stat: FaaS ($REPS reps) ==="
rm -f "$RESULTS_DIR/perf_stat_faas.txt"
perf stat -r "$REPS" -e "$PERF_EVENTS" -o "$RESULTS_DIR/perf_stat_faas.txt" \
    "$PYTHON" FaaS/run_workload.py --num-rides "$NUM_RIDES" > /dev/null
cat "$RESULTS_DIR/perf_stat_faas.txt"

# ---- FlameGraphs: py-spy samples the CPython interpreter stack directly,
# sidestepping perf's kernel-level frame-pointer/DWARF call-graph unwinding
# (which doesn't reliably capture Python stacks, especially under nested
# virtualization like this KVM guest). perf stat above is still the real
# OS-level evidence; py-spy is just for the visual call-stack breakdown.
echo
if ! command -v py-spy > /dev/null 2>&1; then
    echo "=== Installing py-spy ==="
    "$PYTHON" -m pip install --quiet py-spy
fi

echo "=== Recording FlameGraph: Traditional ($FG_RIDES_TRADITIONAL rides) ==="
if py-spy record -o "$RESULTS_DIR/flamegraph_traditional.svg" -- \
        "$PYTHON" Traditional/run_workload.py --num-rides "$FG_RIDES_TRADITIONAL" > /dev/null; then
    echo "Wrote $RESULTS_DIR/flamegraph_traditional.svg"
else
    echo "WARNING: py-spy recording for Traditional failed -- see messages above. Continuing."
fi

echo
echo "=== Recording FlameGraph: FaaS ($FG_RIDES_FAAS rides) ==="
if py-spy record -o "$RESULTS_DIR/flamegraph_faas.svg" --subprocesses -- \
        "$PYTHON" FaaS/run_workload.py --num-rides "$FG_RIDES_FAAS" > /dev/null; then
    echo "Wrote $RESULTS_DIR/flamegraph_faas.svg"
else
    echo "WARNING: py-spy recording for FaaS failed -- see messages above. Continuing."
fi

echo
echo "=== Done -- send back the '$RESULTS_DIR' directory ==="
echo "It contains:"
echo "  $RESULTS_DIR/perf_stat_traditional.txt"
echo "  $RESULTS_DIR/perf_stat_faas.txt"
echo "  $RESULTS_DIR/flamegraph_traditional.svg"
echo "  $RESULTS_DIR/flamegraph_faas.svg"
