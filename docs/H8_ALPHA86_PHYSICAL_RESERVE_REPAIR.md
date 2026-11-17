# H8.6 source/behavior review — native safety after source-to-physical handoff

Date: 17 November 2026. This is **not** approval of final H8 live
acceptance. Different real Anker EMS vs DOEMS forecasts are not a parity
requirement. The requirement is the Alpha84 decision strategy under controlled
inputs, with DOEMS's own 288 quarter prices.

## Evidence and controlled defect
Alpha 8.5 source: `v0.3.0-alpha.8.5`, commit
`a9674b7e82fd7d669b3fec3a6ddbd22279cb6f32`.
Live diagnostics on 16 November demonstrated a safety charge starting after
the first breached reserve quarter; the recorded example had 3 below-reserve
quarters, max 0.2263 kWh gap, remaining 0.2460 kWh AC need and 18 full-horizon
source action windows. This does **not** prove that each of those windows could
be merged without changing price decisions, nor prove that the exact live
forecast was reproduced in a fixture.

A minimal independently constructed price fixture, 288 quarters, 7.2 kWh,
20% start SOC and 0.07 kWh home demand in each of 16 early quarters, gives
two below-reserve quarters in published Alpha 8.5. The first is **14:15 UTC**,
one quarter before the source-selected 14:30 safety charge, with remaining
physical need 0.04442344045368688 kWh. Cheapest earlier usable quarter is
14:00 at EUR 0.09/kWh. Post-replay safety reconciliation inserts that
14:00 action, verifies 2-minute preparation and physical SOC and reduces the
physical need to zero. Existing source's best buy/sell pair and quarter prices
are not changed. The additional safety action is made *before* any
three-slot selection and grouped with neighbors if genuinely contiguous.

## Reviewed source diff for new candidate
`custom_components/doems/planner_72h.py` previous Git blob SHA1:
`4ee35d293f9eb664539e3cbfb8b5d0213a36c639`.
New reviewed candidate SHA1:
`751ae0ac98b454c6f7290700a2d783e571ae7c51`.
The sole production algorithm change is the native
`_reconcile_alpha84_physical_safety` function plus its call after source
window projection; the original Alpha84 hourly source files are byte-identical.
The new function's AST SHA256 is
`de20ca43bfc7ed8aa34701c59d735d3136f3e4bfccfaf66d2de991250820c689`;
the new `calculate_plan72` AST SHA256 is
`e4defa4490b07753f3c125b50423f4df4d342c351894613f11a04c55251e723b`.
All other originally protected source hashes and the frozen mixed-flow
simulator AST remain unchanged.

## Limitations and release gates
- Failing source hashes are updated **only** to this reviewed implementation,
  never dynamically computed from whatever code happens to be present.
- Physical impossibility remains `limited`; source commands can remain
  `limited` after backfill when their original energy target is no longer
  physically needed.
- Continuous low-cost windows remain grouped, while *nonadjacent differently
  priced* selections must not be forcibly fused just to fabricate three
  visually similar commands.
- Require complete two-version green CI plus package SHA256/provenance and
  no main merge. The published 8.5 reference remains intact.
- Real installation, reserve behavior, and Bridge/Store observed statuses
  require independent Home Assistant post-install live verification. Prior
  source-hour screenshots are **not** interchangeable live inputs.
