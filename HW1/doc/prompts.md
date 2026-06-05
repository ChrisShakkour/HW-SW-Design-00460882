# HW1 — AI Tool Usage & Prompt Documentation

Per the assignment, this document records the AI prompts we used to generate and
optimize our code, together with an explanation of the optimization process so we
can clearly justify every change we kept.

**Tool used:** Claude (Anthropic), via Claude Code.

---

## 1. The optimization process (how we got from naive → optimized)

We did not jump straight to an answer. We followed a profile-guided loop, and the
prompts below mirror that loop step by step.

1. **Pick a problem dominated by the memory system, not by arithmetic.**
   We chose the **1×1 convolution** (pointwise conv). Its math is a trivial
   per-pixel dot product over channels, so *performance is decided almost entirely
   by data layout* — the ideal subject for a hardware/software-interplay homework.

2. **Write the textbook (naive) version and reason about its memory access.**
   Standard **NCHW** layout, loop nest `(co, h, w, ci)`. We realized the reduction
   loop over `ci` strides through memory by `H*W` floats (= 64 KB) per step. That
   means: a cache miss on (almost) every multiply-accumulate, a useless hardware
   prefetcher, no vectorization, and the input re-streamed once per output channel.

3. **Form a hypothesis before touching the code.**
   The bottleneck is *how data is fetched*, not *how much arithmetic is done*. So
   the fix must change the access pattern while keeping the math (and output) bit-
   identical. Compiler flags alone cannot help, because the compiler may not
   legally reorder memory accesses across the layout.

4. **Apply the layout transform: NCHW → NHWC.**
   Storing channels contiguously per pixel turns the `ci` reduction into a
   **unit-stride** sweep: one cache line now feeds 16 consecutive MACs, the
   prefetcher streams ahead, and the compiler emits packed FMA (SIMD) instructions.

5. **Add register blocking over output channels (×4).**
   Each loaded input value is reused across 4 output-channel accumulators kept in
   registers, raising arithmetic intensity (FLOPs per byte) so the FMA units stay
   busy → higher IPC.

6. **Make the effect measurable.**
   At small sizes the whole tensor fits in cache and the optimization looks
   pointless. We sized the problem (`Cin=Cout=512`, `H=W=128`, ~32 MB tensors) so
   the working set spills out of L3 and the cache-miss penalty becomes visible.

7. **Verify correctness, then profile.**
   Both versions use an identical deterministic input generator and print a
   layout-independent checksum + sample values, verified byte-identical with
   `diff`. Both are compiled with the **same** flags (`-O3 -march=native`) so the
   speedup is attributable to the optimization, not the compiler.

**Result of the process:** ~6× runtime reduction from a pure data-layout change,
with no change to the algorithm or the output.

---

## 2. Prompts we used

### Prompt 1 — Understanding the task and choosing a problem
> "Here is our HW assignment (attached PDF): we must write a C/C++ program in a
> naive and an optimized version, keep input/output identical, profile both with
> `perf`, and explain the speedup using hardware understanding. Suggest several
> task ideas (not the ones in the PDF) that have a naive version and an optimized
> version with a *meaningful* performance difference, and explain the
> hardware-level reason for each."

### Prompt 2 — Selecting the 1×1 convolution
> "Evaluate a 1×1 convolution (pointwise convolution) as the task. Explain why it
> is a good fit for showing the hardware/software interplay, what the naive
> implementation would look like, what the optimized version would be, and what
> `perf` counters would reveal the difference. Keep it original and tie it to real
> neural-network inference."

### Prompt 3 — Generating the naive version
> "Write the unoptimized C++ 1×1 convolution. Use the standard NCHW layout and the
> natural loop nest so the channel reduction is strided in memory (cache-hostile).
> Use deterministic input generation so the result is reproducible, and print a
> checksum plus a couple of sample output values. Add a `VERBOSE` compile-time
> define (`#define`) that enables/disables all terminal prints so profiling runs
> can be I/O-free. Comment *why* it is slow."

### Prompt 4 — Generating the optimized version
> "Now write the optimized version that produces bit-identical output. Apply two
> changes: (1) transpose the input layout from NCHW to NHWC so the channel
> reduction is unit-stride and vectorizable, and (2) add register blocking over 4
> output channels to reuse each loaded input value. Keep the same deterministic
> inputs, the same checksum/sample output, and the same `VERBOSE` define. Comment
> the hardware insight behind each change."

### Prompt 5 — Guaranteeing identical, verifiable output
> "Make sure the naive and optimized programs are guaranteed to produce identical
> output even though their internal memory layouts differ. Use the same input
> generator in both, and compute the checksum in a layout-independent way so a
> simple `diff` confirms correctness."

### Prompt 6 — Making the performance difference meaningful
> "Our first run showed almost no speedup (60 ms vs 58 ms) because the data fit in
> cache. Help me pick a problem size where the working set spills out of L3 so the
> strided-access penalty actually shows up. Sweep a few sizes, confirm the output
> stays identical, and report the runtimes."

### Prompt 7 — Profiling script
> "Write a `run.sh` that compiles both versions with identical flags
> (`-O3 -march=native`), runs them with prints disabled, diffs their output to
> prove correctness, and then runs `perf stat` on each with counters that tell the
> cache/IPC story (cycles, instructions, L1-dcache-load-misses, LLC-load-misses,
> branch-misses)."

### Prompt 8 — Writing the report
> "Draft the ≤3-page report covering: general approach, the unoptimized
> implementation (why chosen / what it does / why slow / profiling results), the
> optimization (what changed / why / hardware insight / profiling results /
> expected or surprising), and a comparison of the two profiles with reasoning a
> graduate ECE student can follow. Include a short section on approaches we
> considered and dropped."

---

## 3. What we verified ourselves (not just trusted the AI)

- We read and can explain every line of both `.cpp` files, especially the strided
  vs. unit-stride memory access and the register-blocking inner loop.
- We confirmed the two programs print an **identical** checksum and samples via
  `diff` (correctness preserved).
- We confirmed the speedup is real and grows as the working set exceeds cache,
  which is exactly what the cache-locality argument predicts.
- We compiled both with identical flags so the improvement cannot be attributed to
  the compiler.
