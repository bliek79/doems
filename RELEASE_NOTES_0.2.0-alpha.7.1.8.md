# DOEMS 0.2.0-alpha.7.1.8 – Exact Safety Deadline Probes

Prerelease for live validation. R5 remains LIVE RED until explicit user acceptance.

## Problem and resulting behavior

The Automatic safety calculation could exceed its stage budget by repeatedly replaying intermediate quarters for every candidate charging allocation.

Safety candidate trials now evaluate the exact stored-energy effect at the reserve deadline through composed scalar transitions. Automatic stretches between manual target clamps collapse to bounded offset transitions; manual charge/discharge target clamps remain explicit and ordered. Full scalar replay still runs after each accepted allocation. Cheapest-price ordering, latest-slot tie breaking, verified deficit allocation and binary search remain unchanged.

This changes how candidate effects are evaluated, not the economic policy. Native 15-minute / 72-hour / 288-slot inputs, separate Automatic and Combined stages, separate 20-second budgets, manual priority and no-manual Automatic reuse remain unchanged. R0–R4, settings, dashboards, entity names, live battery capacity source and physical execution authority remain unchanged. R5.2/R6 remain closed.

## Validation

124 local tests passed, including the actual historical-source replay reference, randomized scalar/public-route comparisons and exact deadline probes through battery saturation and manual target clamps. Randomized probes agree with full scalar replay within absolute 1e-8 SOC percentage-point tolerance. Equivalent floating-point arithmetic is not a claim of bit-identical plans for all possible inputs.

Private household test inputs and derived measurements are not included in this release. Local checks do not replace Home Assistant live acceptance.

## Diagnostics and live acceptance

`safety_composed_probes` counts deadline evaluations that avoid route replay. Existing safety_replays and safety_replayed_slots count actual scalar replays. Stage wall/CPU diagnostics remain available.

Install this prerelease and restart Home Assistant. Check both planners publish 288 slots and Apex renders, then validate at least two quarter refreshes under the unchanged stage budgets. Test three persistent manual slots, absolute Combined priority and no Automatic restart on a manual-only event. Verify the battery contract's live capacity against its configured source; this release changes no capacity setting. R5 stays LIVE RED until explicit live approval.
