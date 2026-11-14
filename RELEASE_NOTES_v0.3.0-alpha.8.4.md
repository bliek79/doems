# DOEMS 3.0 Alpha 8.4 — Full-chain action window grouping

Replaces the pairwise quarter-command compaction and Alpha 8.3 lower-power
fallback. The whole chronological safety/trade allocation chain is grouped
before commands are built and before the Bridge selects its three-slot preview.
Consecutive allocations with the same action and purpose share one preparation,
one summed energy requirement, upward-rounded 10 W power and an energy-derived
command target. Gaps, direction/purpose changes and the existing maximum runtime
remain boundaries. The source resolution remains 15 minutes (Alpha84 uses hours).

Plan72 remains the only full SOC/energy engine. It replays the complete grouped
command chain, including target arrival before the maximum window duration.
Command target and projected end SOC remain separate. Group allocation energy
is explicit and the Bridge validates its power/target relationship against the
replayed segments; it does not independently optimize or simulate the route.
Unchanged singleton commands and protected persisted plans retain their contract.

The frozen Alpha84 Bridge now runs as a test oracle: eight consecutive source
allocations produce one candidate with matching duration, upward-rounded power,
energy and target (within Alpha84's published precision). A second end-to-end
case verifies twenty source allocations become five windows before the preview
exposes three and retains two overflow candidates. Near-full target arrival and
future household energy are covered without the former lower-power fallback.

Full command replay can reveal later reserve deficits after an early target
stop. These remain reported as `limited` and actual shortfall; no tolerance is
relaxed and no energy is invented. Tests explicitly exercise this outcome,
including a variable-load/solar route with approximately 0.0124 kWh shortfall.
This release does not claim every feasible source allocation remains a `ready`
physical command route or that the user's complete live forecast was replayed.

Physical execution authority and execution remain false. No dashboard changes,
new entity IDs, changes to main, or replacement of previous tags/releases.
Live acceptance of the entire action-window chain is still required.
