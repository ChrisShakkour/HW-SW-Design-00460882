#!/usr/bin/env bash
# =============================================================================
# run.sh -- compile, run, verify, and profile both 1x1-conv versions.
#
# Both versions are compiled with the SAME flags (-O3 -march=native) so any
# measured difference is due to the data-layout / cache / register-blocking
# optimization, NOT compiler flags. VERBOSE=0 disables all progress prints so
# stdout contains only the RESULT line (clean for diffing and for perf).
# =============================================================================
set -euo pipefail

CXX=${CXX:-g++}
CXXFLAGS="-O3 -march=native -std=c++17 -DVERBOSE=0"

echo "=== Compiling (flags: $CXXFLAGS) ==="
$CXX $CXXFLAGS src/conv1x1_naive.cpp -o conv1x1_naive
$CXX $CXXFLAGS src/conv1x1_opt.cpp   -o conv1x1_opt

# ---- Correctness: outputs must be IDENTICAL --------------------------------
echo
echo "=== Verifying identical output ==="
./conv1x1_naive > out_naive.txt
./conv1x1_opt   > out_opt.txt
if diff -q out_naive.txt out_opt.txt > /dev/null; then
    echo "OK: outputs are identical"
    cat out_naive.txt
else
    echo "MISMATCH between versions:"
    diff out_naive.txt out_opt.txt || true
    exit 1
fi

# ---- Profiling with perf ----------------------------------------------------
# Counters chosen to tell the cache/IPC story:
#   cycles, instructions         -> IPC
#   L1-dcache-load-misses        -> spatial locality of the reduction
#   LLC-load-misses              -> how often we fall all the way to DRAM
PERF_EVENTS="cycles,instructions,L1-dcache-loads,L1-dcache-load-misses,LLC-loads,LLC-load-misses,branch-misses"

echo
echo "=== perf stat: NAIVE ==="
perf stat -e "$PERF_EVENTS" ./conv1x1_naive > /dev/null

echo
echo "=== perf stat: OPTIMIZED ==="
perf stat -e "$PERF_EVENTS" ./conv1x1_opt > /dev/null

# Optional: detailed cache breakdown
# perf stat -d ./conv1x1_naive > /dev/null
# perf stat -d ./conv1x1_opt   > /dev/null
