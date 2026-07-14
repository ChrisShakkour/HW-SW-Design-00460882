# Part 3 — Feature Extension: Automatic Driver Reassignment

## The feature

**When a driver cancels mid-ride (status `MATCHED` or `IN_PROGRESS`), automatically
find a replacement driver and keep the ride alive, instead of leaving the rider
stranded with a `CANCELLED` ride.**

Chosen because it isn't a new isolated operation — it necessarily *composes*
two things that already exist (freeing a driver, and re-running matching), so
it directly probes how each architecture handles cross-operation composition,
which is exactly what the assignment asks to evaluate.

## What changed — Traditional

**Files touched:** 1 (`Traditional/ride_system.py`).
**New code:** one ~20-line method, `handle_driver_cancellation_with_reassignment`,
plus a 2-argument addition (`exclude_driver_id`, defaulting to `None`) to the
existing `match_driver_to_rider` signature so a freshly-freed driver isn't
immediately re-offered the ride they just abandoned.

```python
def handle_driver_cancellation_with_reassignment(self, ride_id: str) -> dict:
    old_driver_id = ride.driver_id
    ... free old driver, reopen ride ...
    match_result = self.match_driver_to_rider(ride_id, exclude_driver_id=old_driver_id)
    return {"status": "REASSIGNED", ...} or {"status": "WAITING_FOR_DRIVER"}
```

The new method simply *calls another method on the same object*. There is no
serialization, no new process, no new coordination mechanism — `self.drivers`,
`self.rides`, and `self.vehicles` are the same live Python dicts both methods
already share. This is the cheapest possible kind of change: additive, local,
and it cannot silently break anything outside this one file because nothing
else needed to be touched to wire it in.

## What changed — FaaS

**Files touched:** 2 — one **new** file (`FaaS/functions/reassign_ride.py`,
~80 lines) and a small edit to an existing one (`match_driver_to_rider.py`,
same `exclude_driver_id` parameter, ~4 lines).

The interesting part is *why* a new file was unavoidable. Every one of the
other 12 functions is independent by design — `request_ride.py` has zero
knowledge that `match_driver_to_rider.py` exists, and vice versa. That
independence is what "minimal dependencies between functions" (an explicit
FaaS principle in the assignment) means in practice. But this feature
*requires* two steps to happen in sequence: free the old driver, then
re-run matching. There is no way to express "then call the matching logic"
without one of:

1. **Duplicating** the matching logic inside the cancellation path (violates
   DRY, now two copies of matching logic to keep in sync), or
2. **Directly invoking another function from within a function** (the
   approach taken here — `reassign_ride.py` shells out to
   `match_driver_to_rider.py` as a subprocess), which quietly breaks the
   "independent function" invariant the other 12 functions were built to
   respect, or
3. **Introducing a real coordination layer** (a queue, an event-bus rule, a
   Step-Functions-style state machine) — the architecturally "correct" FaaS
   answer, but a new category of infrastructure this project didn't need
   until this feature was requested.

`reassign_ride.py` takes option 2 to keep the demo runnable without adding a
message broker, and says so in its own docstring — but option 2 is exactly
the kind of shortcut that, in a real serverless deployment, reintroduces
tight coupling between "independently" deployed functions (now you can't
change `match_driver_to_rider`'s CLI contract without also touching
`reassign_ride.py`, and a failure in the subprocess call is much harder to
observe/retry than an in-process exception).

## Discussion

**How many parts of the system had to change?**
Traditional: 1 file, 0 new files, 0 new concepts.
FaaS: 2 files, 1 of them entirely new, and — more importantly — a new
*category* of function (an orchestrator) that didn't exist in the original
12. Every prior FaaS extension (any of the first 12 operations) touched
exactly one file, mirroring Traditional's one-method-per-operation pattern.
This feature is the first one where that symmetry breaks down.

**How risky is the modification?**
Traditional: low. The change is additive (a new method), doesn't alter any
existing method's behavior for existing callers, and is exercised entirely
in-process — a bug here can misbehave, but it can't fail silently across a
process boundary or leave state half-written if the process crashes mid-call.

FaaS: meaningfully higher. `reassign_ride.py`'s step 1 (free driver, reopen
ride) writes state to disk; step 2 is a *separate process invocation* of
`match_driver_to_rider.py`. If that subprocess call fails or the machine dies
between steps 1 and 2, the ride is left `REQUESTED` with no driver and no one
retrying — a partial-failure state that cannot happen in the Traditional
version, where both steps run under one Python call stack. This is a direct,
concrete instance of the "risk of bugs/failures affecting the system"
question from Part 5: composed FaaS operations need their own retry/idempotency
story that a monolith gets for free from the language runtime.

**Which architecture is easier to extend?**
Traditional, for this feature, decisively. The FaaS version works (see
`tests/test_feature_extension.py`), but only by bending the architecture's
own stated principle (independent functions) — which is itself the finding:
FaaS is cheap to extend *as long as new features stay within a single
function's boundary* (e.g., changing `calculate_fare`'s formula is equally
trivial in both architectures). The moment a feature needs *sequencing*
across what were previously independent triggers, FaaS either needs new
infrastructure (a real orchestrator/event bus) or has to compromise the
independence that was the point of choosing FaaS in the first place.
