# Part 4 — Performance Evaluation

## Methodology

**Workload:** both `Traditional/run_workload.py` and `FaaS/run_workload.py` run the identical deterministic scenario — a fixed fleet of 5 drivers and a cycling set of 5 pickup/dropoff coordinate pairs — driving each ride through the full lifecycle: `request_ride → match_driver_to_rider → start_trip → complete_trip → process_payment → rate_and_review` (6 operations/ride). For the numbers below, both architectures processed **200 rides** (1,200 total operations), and both produced the exact same result (`completed=200 total_fare=2028.00`), so the comparison below is apples-to-apples on functionally identical work.

**Tools:**
- **`perf stat -r 5`** for the OS-level counters (cycles, instructions, context-switches, page-faults, wall time), averaged over 5 repetitions.
- **`py-spy record --subprocesses`** for the call-stack flamegraphs, in place of `perf record -g`. `perf record`'s frame-pointer/DWARF call-graph unwinding did not reliably capture Python stacks in our environment (a KVM guest under nested virtualization) — it produced 0 usable samples for the fast Traditional run and empty stack data for both. `py-spy` samples the CPython interpreter's frame stack directly, sidestepping kernel-level unwinding entirely, and was used for the flamegraph portion only; `perf stat`'s numbers are unaffected by this and are used as-is.
- Environment: Ubuntu (KVM guest, `qemu-system-x86_64 -cpu host -accel kvm`), Python 3 (system interpreter), both architectures profiled on the same machine back-to-back.

## Results: `perf stat` (200 rides, mean of 5 runs)

| Metric | Traditional | FaaS | FaaS / Traditional |
|---|---|---|---|
| Wall time | 0.0790 s | 78.294 s | **~992x** |
| Cycles | 180,586,466 | 175,852,925,081 | **~974x** |
| Instructions | 251,989,811 | 230,822,559,530 | **~916x** |
| IPC (insn/cycle) | 1.39 | 1.31 | ~0.94x (roughly equal) |
| Context-switches | 16 | 34,257 | **~2141x** |
| Page-faults | 1,941 | 2,367,004 | **~1219x** |
| CPU utilization | 0.973 CPUs | 0.968 CPUs | ~equal |

## Which architecture performed better, and why

**Traditional wins by roughly three orders of magnitude on every metric that measures work done**, while IPC and CPU-utilization — the metrics that measure *efficiency per instruction executed* — are nearly identical between the two. That distinction is the entire story:

- IPC being close (1.39 vs 1.31) means the CPU isn't struggling more per-instruction in FaaS — there's no cache-thrashing or branch-misprediction story here.
- The ~974x more cycles and ~916x more instructions mean FaaS is doing that much more *total work* for an identical result. That work isn't business logic (the actual matching/fare/payment computations are the same few hundred lines either way) — it's **1,205 separate Python interpreter cold starts** (200 rides × 6 operations, plus 5 initial driver clock-ins), each one re-parsing bytecode, re-importing `argparse`/`json`/`state_store`, and re-initializing the CPython runtime from scratch, only to run a handful of lines of actual logic and exit.
- The **context-switch** (~2141x) and **page-fault** (~1219x) numbers are the OS-level fingerprint of exactly that: every `subprocess.run()` call is a `fork()`+`exec()` — a new address space, a new set of page tables faulted in from scratch, a new process the scheduler has to context-switch into and out of. Traditional never leaves its own single process, so these numbers stay near zero (16 context-switches and ~1,941 page-faults for the *entire* 200-ride run, most of which is just normal Python startup for the one process).
- Dividing FaaS's 78.3s by 1,205 operations gives **~65ms per operation** — squarely in the range of a cold Python interpreter start, not of running a few lines of matching/fare-calculation code.

This is exactly the tradeoff the FaaS architectural model is known for in real deployments: real cloud FaaS platforms fight this same cost with warm pools/pre-provisioned execution environments precisely because a cold interpreter/runtime start dominates short-lived function invocations. Our subprocess-per-call design has no such warm-pool mechanism — deliberately so, to make the actual cost mechanism visible rather than hidden.

## FlameGraph findings

Both are in `perf_results/flamegraph_traditional.svg` and `perf_results/flamegraph_faas.svg`.

**Traditional** (136 distinct stack frames captured over its ~0.08s run): dominated by the `run_workload.py` loop calling into `request_ride`/`match_driver_to_rider`, but a genuinely notable chunk — roughly half of all sampled frames — passes through **`dataclasses.asdict()` / `_asdict_inner`**. Every operation converts its result from a dataclass instance to a plain dict via `asdict()`, which is a relatively expensive *recursive* walk. This is a real, minor, and fixable hotspot the flamegraph surfaced that we would not have otherwise noticed — utterly dwarfed by FaaS's overhead, but worth noting as a finding the profiling actually produced rather than assumed.

**FaaS** (5,627 stack frames captured across ~300+ separate short-lived subprocess trees, since `py-spy --subprocesses` gives each spawned process its own root in the graph): **~61% of all captured frames (3,426 of 5,627) sit inside `<frozen importlib._bootstrap...>`** — Python's module import machinery. This is the visual, per-invocation confirmation of what `perf stat`'s context-switch/page-fault numbers already proved in aggregate: the majority of each FaaS operation's lifetime is spent starting the interpreter and importing modules, not executing `handler()`.

## Conclusion

The two profiling tools tell a single, consistent story from two different angles: `perf stat` proves the aggregate OS-level cost (a ~1,000x wall-time and cycle-count penalty, with context-switches and page-faults scaling even faster than that), and the flamegraphs show *why* — FaaS's per-operation cost is overwhelmingly interpreter cold-start and import overhead, not the business logic, which is nearly identical in complexity to the Traditional side. This directly reinforces the [Part 3](part3_feature_extension.md) finding from a different angle: FaaS's architectural cost isn't just "harder to extend when composition is needed" — it's also "structurally expensive per call," because every one of the "independent, stateless" functions pays a full interpreter-startup tax that a monolith never has to pay at all.
