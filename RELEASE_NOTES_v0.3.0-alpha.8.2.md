# DOEMS 3.0 Alpha 8.2 — Alpha84 orchestration corrections

Corrects the chapter-8 observer chain before further live acceptance.

- Retains the published Plan72 generation during background recalculation; true source loss still invalidates the source.
- Scheduler selects persistent slots independently of planner readiness, as Alpha84 does. Source consistency and blockers remain diagnostic; selection is never physical execution permission.
- Automatic plans written by the bridge use Alpha84's 10-minute start margin. Hard planned end times still apply. Existing due/active slots are protected; future slots are reconciled through the existing writer.
- Removes the extra completion-time quarter rejection. Superseded input generations and fingerprints are still rejected.
- Enables content-change triggers and one-shot near/due automatic-start triggers. Ordinary SOC changes remain deferred; critical reserve crossings and effective manual constraint changes remain exceptions.
- Retains coherent cached horizons in Bridge and writer. Past candidates are not newly assigned; identity, signature and storage revision checks remain.
- Removes safety-compaction restrictions requiring one clock hour and identical tariffs, and its extra no-cost-increase condition. Full Plan72 replay retains capacity, reserve, manual-plan and solar protections; trading profitability checks remain.
- Adds progress, duration, requested generation and discarded-result diagnostics to the existing Plan72 entities. No entity IDs or unique IDs are changed.

Physical execution authority and execution enabled remain false. Chapters 9–12 are not implemented here. Dashboards and main are unchanged.

Live acceptance must be repeated, especially automatic start margins, selection while calculating, cancellation, source diagnosis and contiguous load windows. B.R.I.C.K. has not been established as the cause of the earlier delay. This patch does not claim a measured reduction in live compute duration.
