# DOEMS 3.0 alpha.7.4 — Alpha84 safety-price ordering

The former practical-window safety allocator strengthened/extended an existing
command before considering cheaper feasible quarters. It could therefore create
long low-power charges across expensive periods. Adjacent command compaction
could also redistribute charging energy across price boundaries.

Safety allocations now follow Alpha84's price-first, latest-on-equal-price
ordering before each chronological reserve deadline. Existing commands do not
outrank cheaper alternatives. All preceding feasible quarters are considered;
the former cheapest-32/latest-16 shortcut is removed. Independent allocation
quarters are only compacted across a single import tariff, without increasing
route cost, displacing solar or invalidating downstream command capacity.
Cheaper earlier allocations also reconcile superseded downstream setpoints in
the same SOC simulation. Setpoints stay in 10 W increments, with complete power
phases and the existing two-minute preparation.

## Verification boundary

The frozen upstream Alpha84 planner_preview.py is included only in tests, with
its original license, commit and SHA-256. Tests execute that unmodified strategy
code to check cheaper reachable windows and necessary earlier bridge charging.
Regression scenarios cover the demonstrated expensive-extension and tariff-
smearing defects. Existing manual, restart, reconciliation, stale-input,
Combined/SOC, energy-conservation, reserve and trading protections remain.

The previous test's arbitrary <20 full-horizon command count rewarded the faulty
long-window extension. It is replaced by the physical 288-quarter bound; the
three persistent live slots and overflow behavior remain unchanged. No minimum
reserve, energy conservation, full-power-phase or release-integrity assertion
is removed. Only the two reviewed corrected algorithms and the complete planner
blob receive new frozen digests; other algorithm digests remain unchanged.
The replay budget is bounded at 8192 to cover the restored quarter allocations;
checked interpolation and minimum-setpoint probing limit unnecessary replays.

Alpha84's hourly preview is an oracle for strategic decisions, not an assertion
of identical numerical hourly trajectories: DOEMS retains its required native
72-hour/288-quarter timeline, physically disjoint energy flows, fixed preparation,
manual priority and existing Action Bridge. Trading remains constrained by the
existing route-cost, margin, solar and reserve protections.

No entities, unique IDs, dashboard visuals or existing tags are changed.
No Home Assistant installation is modified. No physical execution authority is
introduced. Publication is conditional on the full Python 3.12 and 3.13 suites
and release validation passing in GitHub Actions.

Local verification: 285 tests passed on Python 3.12 and 285 on Python 3.13;
compile and release-source validation passed on both versions. Live Home
Assistant validation has not been performed and remains open.
