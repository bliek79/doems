# DOEMS 3.0 — Basisherstel H5–H8 (20 november 2026)

**Status: DEVELOPMENT ONLY. Not released, no HA modification, chapter 8 NOT signed off.**
Base: `v0.3.0-alpha.8.7` / `ff5b80a572fecc701807f5d9dab7fc162fd6f5d2`.
Original strategy oracle: `bliek79/dummy-os-anker-ems` `0.0.1-alpha.84` /
`6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d`.
Approved Plan Store starting point: `v0.3.0-alpha.7.8` /
`bc348852c8254eba51d159ca84f1a0d2fbecf736`.

## Original responsibilities and required correction

| Source of truth | Owns | Must NOT own |
| --- | --- | --- |
| Alpha84 strategy (energy need, preview, 72h source, original 3-slot priority) | Cheapest feasible safety allocation before deadline, one best chronological price trade pair, priorities | HA device control, manual slot mutations |
| DOEMS forecast/prices adapter | 288 native quarters/72h; separate import and export, no blending | Any competing safety or trade strategy |
| Native Plan72 | One causal quarter-accurate physical battery energy/SOC replay, 2-min preparation, measured SOC/limits, actual shortfalls | Unreviewed new independent economic policy |
| Action Bridge | Validity, exact source, chronological safe prefix | New trading/charging strategy |
| Plan Store | Three persistent slots, revision/identity, manual/due/active protection, terminal cleanup | Economic optimization or physical execution |
| Scheduler | One ready/due slot, Alpha84 order | New plan generation, energy/SOC optimization or battery execution |

**Important:** A 15-minute decision may legitimately differ from a 60-minute one
because it has more precise timestamps and prices. Do NOT assert identical
live source curves or same slot start times when forecasts or granularity differ.
Controlled tests should compare original decision priority and invariants,
and separately record physically expected differences.

## Confirmed drift and repairs at this checkpoint

### H5/8 source energy loss at a quarter handoff
The original H8.7 `alpha84_planning.build_72h_plan_preview` publishes every
source quarter in three decimals. A 0.0375-kWh demand becomes 0.037 kWh in
Python's round-to-even, so a real 0.150-kWh hour was published as 0.148 kWh.
This is an **incorrect energy handoff**, not an intended quarter-price policy.
A synthetic 72-hour reference previously counted 137 hourly source mismatch
fields; 72 were affected by that source per-quarter discharge rounding alone.
The source now retains six decimals for 15-minute *output* fields while
preserving exactly the original three-decimal hourly output. The pure
original Alpha84 hourly oracle remains frozen.

The baseline test's residual 65 source/hour discrepancies include shifted
safety-charge timing and SOC projections. These remain **open review
items**; counting differences does not, by itself, prove an incorrect rule
when the original uses hours and DOEMS uses quarters. Existing diagnostics
used to *print* differences while always exiting zero, and MUST NOT be used
as a green acceptance statement.

### H7 persistent slot exhaustion from terminal manual states
The original Alpha84 `plan_store.py` treats empty or terminal
(`geannuleerd`, `voltooid`, `fout`) manual plans as reusable.
In DOEMS H7.8 and H8.7, both `plan_slot_assignment` and `plan_store`
instead permitted only manual `concept` + action `geen`, even though
the unchanged original `alpha84_action_bridge._manual_slot_available`
accepted the terminal statuses. This **contradictory policy** trapped
slots after cancellation.

Actual Home Assistant observation: 12 Plan72 action windows; Store
status `ready`, reason `unchanged`, overflow `11`;
slot 1 automatic pending; slots 2 and 3 manually-originated,
action `geen`, lifecycle `geannuleerd`.
Do not infer Bridge state from `unknown` entities until actual IDs
are identified; Store overflow makes the assignment problem explicit.

The corrected assignment and Store now accept terminal manual
plans (including a still-present cancelled action) but never overwrite
a manual `pending` or `actief` action. The real writer and restart
regressions reproduce the three-slot refill.

## Publication and acceptance gates

1. Two Python versions and immutable source hashes, plus tests covering the
   original 60-minute policy and true native 288-quarter input. Add a Python
   3.14 environment check before signing off live HA performance.
2. Controlled same-input comparisons must differentiate output rounding,
   quarter-resolution timing, true safety/trade policy differences and 2-minute
   physical start loss. Counts alone are not sufficient.
3. Native Plan72, Bridge and Store must derive candidates from one matching
   generation and fingerprint, and the Store must refill all genuinely free slots.
4. Verify runtime actual compute duration/stale results; the 19 Nov HA bootstrap
   timeout contained an outstanding Plan72 executor task. Do not attribute all
   system startup delay to DOEMS without profiling.
5. Validate live Home Assistant 72-hour action windows, eligible Bridge
   candidates, three slots and planned SOC after installation. No blanket
   demand for exactly three actions when fewer are valid.
6. `execution_enabled=false` and `physical_execution_authority=false`
   remain nonnegotiable; no direct Home Assistant changes in this branch.

This document is a recovery checkpoint, **not** proof that the entire native
quarter-price planner already matches every original Alpha84 strategy decision.

## Native Plan72 bootstrap boundary (HA / Python 3.14)
The user-provided 19-Nov log showed `Plan72Runtime._run_worker` outstanding
in Home Assistant's bootstrap wait; this is not proof that the code alone
caused every startup delay. Home Assistant's current documented async contract
says `hass.async_create_task` is awaited during startup, whereas
`hass.async_create_background_task` is not. The runtime now launches its
long-running, pure 288-quarter calculation as a named **background** task,
with unchanged generation/fingerprint verification, cancellation on
integration unload, and no battery authority. This does NOT speed up the
calculation itself. It prevents that calculation from directly keeping HA in
the bootstrap wait bucket. Reference:
https://developers.home-assistant.io/docs/asyncio/
(which redirects to https://contributors.home-assistant.io/core/internals/asyncio/).
The test boundary asserts background scheduling and shutdown cancellation,
and the branch extends verification to Python 3.14 as seen in the actual log.

## CI discovery: existing fixed number was based on old source precision
The initial full-suite run after quarter-source precision correction reported
**938 passed, one failed** on both Python 3.12 and 3.13. The failing test was
the prior hardcoded safety-window request `2.071 kWh`, which now becomes
`2.051 kWh` when the 15-minute source flows are no longer individually
rounded to 3 decimals. This expected numeric was not a frozen upstream
Alpha84 strategic decision; it was a projected physical input from the old
rounding implementation. The test has been strengthened to compare actual
source quarter safety energy with requested energy from the matching
physical window, *while retaining its downstream reserve and completion
checks*. The independent direct original-hourly strategy oracle and the
new first-4-quarter 0.150-kWh preservation gate are not relaxed. CI must
run again; failure remains a release blocker.
