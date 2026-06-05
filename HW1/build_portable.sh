#!/usr/bin/env bash
# Build portable Linux binaries (AVX2+FMA, no -march=native) for running perf
# on a different x86-64 server. Run this where g++ is available; copy bin/ over.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p bin
FLAGS="-O3 -mavx2 -mfma -std=c++17 -DVERBOSE=0"
g++ $FLAGS src/conv1x1_naive.cpp -o bin/conv1x1_naive
g++ $FLAGS src/conv1x1_opt.cpp   -o bin/conv1x1_opt
echo "built: bin/conv1x1_naive bin/conv1x1_opt"
