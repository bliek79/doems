# DOEMS 0.2.0-alpha.7.1.7 – Historical Safety Replay

Prerelease for live validation. R5 remains LIVE RED until explicit user acceptance.

## Problem and resulting behavior

Alpha.7.1.6 live diagnostics locate all three timeouts in Automatic safety charging. Energy construction took 0.09–0.26 seconds; safety charging took 19.57–19.89 seconds. One attempt performed 1,633 complete route simulations. CPU contention also reduced available worker CPU time.

The safety computation now adapts the actual pre-reset DOEMS alpha.39 scalar cheapest-energy replay. Safety probes calculate battery state and available charging room instead of repeatedly constructing full planner rows. Trials stop at the reserve deadline. A direct deficit allocation is checked against the actual SOC path; where intervening consumption or target clamps make its effect nonlinear, the historical 18-step binary search selects sufficient charging. The historical bounded repair limit of four times the slot count is retained alongside the unchanged cooperative 20-second stage budget.

## Exact source and deliberate adaptations

- Repository bliek79/doems, tag 0.1.0-alpha.39.
- `custom_components/doems/ems_alpha36/planner_preview.py`: `_simulate_safety`, cheapest feasible earlier-window ordering and binary allocation search.
- `custom_components/doems/ems_alpha36/sequential_safety.py`: direct deficit repair and deadline-limited replay.
- The historical preview source is included unchanged as a test-only fixture, SHA256 `2baf0409efe7e0c53789de43e47c2c7e38afb2c3f7252acd4d2840080f40109d`.
- The old 72-hour compatibility adapter is not restored. All 288 quarter inputs and real quarter prices remain independent.
- Current technical 5% discharge, software-reserve target, PV priority, configurable capacity/efficiencies/power and exact manual overlap/target clamps remain authoritative. The old 0.01-kWh observation threshold is not imported into current quarter discharge behavior.
- Historical Plan Store writes, scheduler and execution connections are not imported. Automatic remains independent; Combined handles manual priority.
- The current separate economic-home and optional export planning remain in place. This ports the failing safety calculation, not every historical economic policy.

## Diagnostics

Existing phase wall/CPU measurements remain. `safety_replays`, `safety_allocation_probes` and `safety_replayed_slots` count lightweight probes separately. `planner_simulation_count` counts full-horizon route replays; deadline-only probes no longer inflate that count. No prefix-cache optimization is included.

## Local validation

- 123 tests passed, including executable historical-source comparison, twelve randomized native replay comparisons with three manual targets, nonlinear allocation, 288-slot publication, independent Automatic/manual-priority Combined, async sequencing, recovery and budget-failure publication.
- Three constant-demand 72-hour datasets (0.025, 0.10 and 0.25 kWh per quarter, 7.2 kWh capacity, 26% initial SOC): Automatic total time reduced from 0.924/1.174/1.019 seconds to 0.263/0.273/0.184 seconds. Total safety energy and minimum SOC matched alpha.7.1.6 on these datasets.
- These are local synthetic measurements on Python 3.12, not a replay of the unavailable live forecast dataset or a guarantee for Home Assistant's Python 3.14/runtime load. Broader tests verify contracts; they do not claim every old and new plan is numerically identical because nonlinear allocation is corrected.

## Live acceptance remains open

Install and restart. Validate Automatic then Combined both publish 288 slots, Apex renders, and at least two quarter boundaries complete within the existing stage budgets. Then validate three persistent Manual slots and economic SOC against the old Anker EMS. R0–R4 remain frozen; R5.2/R6 remain closed. Only explicit user acceptance can make R5 live green.
