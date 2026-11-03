# DOEMS 3.0 — v0.3.0-alpha.7.8

## Automatic slot refill after cancellation

A reusable automatic slot could remain cancelled when the Action Bridge selected the same candidate again. The persistent store skipped the write on equal planner signatures without checking the lifecycle state. The writer consequently reported ready although the slot remained terminal.

Equal signatures now skip storage only when the intended lifecycle also matches. A terminal automatic slot selected again is written as a concept and passes through the existing storage-only handoff to pending. Chronological candidate selection, overflow semantics, manual ownership and active-slot protection are retained. Cancellation releases an automatic slot; it does not blacklist its candidate.

## Verification

The new parameterized integration regression executes the actual writer and durable store for cancelled, completed and faulted automatic slots. All three cases failed before the fix. The fixed cases verify refill using the same signature, unchanged manual and surviving automatic slots, unique assignments, correct overflow, restart persistence and zero additional writes on repeated synchronization.

The reviewed plan_store.py blob is updated solely for this lifecycle-aware no-op condition. Existing planner, runtime, Action Bridge and strategy regression freezes remain unchanged. Full Python 3.12 and 3.13 suites, release validation and package provenance checks are required before publication.

## Scope

No entity or unique ID changes. Existing release tags are retained. No dashboard or Home Assistant installation changes. Physical execution remains disabled. Live chapter-7 test 5 must be repeated after installation; the remaining live checks and the old Combined dashboard connection are not declared complete by this release.
