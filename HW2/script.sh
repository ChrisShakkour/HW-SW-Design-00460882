#!/usr/bin/env bash
# =============================================================================
# script.sh -- install deps, run the correctness test suite, run the shared
# deterministic workload against both architectures, verify they agree, then
# profile both with perf (Part 4). Run from anywhere; it cds to its own dir.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
NUM_RIDES=${NUM_RIDES:-50}

echo "=== Installing test dependencies (pytest) ==="
"$PYTHON" -m pip install --quiet pytest

echo
echo "=== Running correctness test suite (pytest) ==="
"$PYTHON" -m pytest tests/ -v

# ---- Shared deterministic workload: same fleet/rides fed to both -----------
echo
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
if command -v perf > /dev/null 2>&1; then
    PERF_EVENTS="cycles,instructions,context-switches,page-faults,cpu-clock"

    echo "=== perf stat: Traditional ==="
    perf stat -e "$PERF_EVENTS" "$PYTHON" Traditional/run_workload.py --num-rides "$NUM_RIDES" > /dev/null

    echo
    echo "=== perf stat: FaaS ==="
    perf stat -e "$PERF_EVENTS" "$PYTHON" FaaS/run_workload.py --num-rides "$NUM_RIDES" > /dev/null

    echo
    if command -v stackcollapse-perf.pl > /dev/null 2>&1 && command -v flamegraph.pl > /dev/null 2>&1; then
        echo "=== Recording FlameGraphs (requires brendangregg/FlameGraph on PATH) ==="
        perf record -F 999 -g -o perf_traditional.data -- "$PYTHON" Traditional/run_workload.py --num-rides "$NUM_RIDES" > /dev/null
        perf script -i perf_traditional.data | stackcollapse-perf.pl | flamegraph.pl > flamegraph_traditional.svg

        perf record -F 999 -g -o perf_faas.data -- "$PYTHON" FaaS/run_workload.py --num-rides "$NUM_RIDES" > /dev/null
        perf script -i perf_faas.data | stackcollapse-perf.pl | flamegraph.pl > flamegraph_faas.svg

        echo "Wrote flamegraph_traditional.svg and flamegraph_faas.svg"
    else
        echo "FlameGraph scripts (stackcollapse-perf.pl / flamegraph.pl) not found on PATH."
        echo "perf stat results above are still valid; install github.com/brendangregg/FlameGraph for SVGs."
    fi
else
    echo "perf not found on this system -- skipping Part 4 profiling."
    echo "Run this script on a Linux machine with perf installed to collect profiling data for the report."
fi

echo
echo "=== Done ==="
