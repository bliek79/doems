# DOEMS 0.2.0-alpha.7.1.6 – Planner Runtime Diagnostics

Diagnostic prerelease for repeated live Automatic Planner work-budget timeouts in alpha.7.1.5. This release does not claim to fix the planner's excessive runtime or make R5 live green.

## Changed
- Record worker wall time and worker-thread CPU time, phase durations and simulation/safety/economic trial counts.
- Measure Energy forecast construction, model validation/setup, safety charging, economic home planning, export trade planning, final output and publication preparation separately.
- Publish compact `planner_automatic_diagnostics` and `planner_combined_diagnostics` on existing planner sensors. On a timeout, retain the interrupted phase and partial counters and write one diagnostic warning; no historical source records or native-slot dumps are logged.

## Fixed
- Publish the elapsed duration of the failed attempt before writing its blocked snapshot, instead of pairing the current timeout with the previous attempt's duration.

## Unchanged
- Native 15 minutes / 72 hours / 288 slots, independent Automatic, persistent Manual R2–R4 and manual-priority Combined.
- Automatic then Combined sequence, no-manual route reuse, per-stage cooperative 20-second budget and current-generation publication gates.
- Forecast formulas, economic policy, options, source IDs, public entity identities, dashboard, frozen R0–R4 files and physical execution flags.
- The experimental local prefix optimization is not included. R5.2 and R6 remain closed.

## Validation
- Existing full regression suite and frozen-file hash gates, plus numerical-output parity with diagnostics enabled, partial safety-timeout evidence, and the actual async manager's current-duration failure publication.
- Live validation remains required: after installation and restart, allow one quarter refresh and share Automatic/Combined diagnostic attributes and the timeout warning. R5 remains LIVE RED until explicit user acceptance.
