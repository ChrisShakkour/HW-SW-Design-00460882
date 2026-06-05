#!/usr/bin/env bash
# =============================================================================
# perf.sh -- profile the PREBUILT binaries in bin/ with perf. No compilation,
# so this runs on a server that has perf but not g++.
#
# Usage:  ./perf.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

NAIVE=bin/conv1x1_naive
OPT=bin/conv1x1_opt

if [[ ! -x "$NAIVE" || ! -x "$OPT" ]]; then
    echo "ERROR: binaries not found in bin/. Build them first (build_portable.sh) and copy bin/ here." >&2
    exit 1
fi

# ---- Correctness: outputs must be IDENTICAL --------------------------------
echo "=== Verifying identical output ==="
"$NAIVE" > out_naive.txt
"$OPT"   > out_opt.txt
if diff -q out_naive.txt out_opt.txt > /dev/null; then
    echo "OK: outputs are identical"
    cat out_naive.txt
else
    echo "MISMATCH between versions:"; diff out_naive.txt out_opt.txt || true; exit 1
fi

# ---- Profiling with perf ----------------------------------------------------
PERF_EVENTS="cycles,instructions,L1-dcache-loads,L1-dcache-load-misses,LLC-loads,LLC-load-misses,branch-misses"

echo
echo "=== perf stat: NAIVE ==="
perf stat -e "$PERF_EVENTS" "$NAIVE" > /dev/null

echo
echo "=== perf stat: OPTIMIZED ==="
perf stat -e "$PERF_EVENTS" "$OPT" > /dev/null
