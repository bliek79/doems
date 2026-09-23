# DOEMS 0.1.0-alpha.18 - Step 13 G5 Frozen Live Parity

## Scope
Step 13 adds the frozen-live G5 parity gate to the standalone DOEMS integration. It proves that the current DOEMS EMS decision path reproduces the pinned Alpha76 decision baseline on one immutable real live snapshot.

Step 12.7 Live Shadow Acceptance remains open asynchronously and is not replaced by G5.

## Decision policy baseline
- Current EMS policy is labeled `alpha76_baseline_v1`.
- G5 does not change Energy Need, reserve, safety charging, Solar Charge Delay, trade, Plan72 or execution policy.
- Future policy improvements remain possible, but only as explicit versioned policy changes with separate design, validation, routebaseline update and user approval.
- Safety/architecture invariants remain independent of policy tuning.

## Added
- Pure `ems_g5_live_parity.py` comparator.
- Persistent per-entry G5 evidence store under `doems.<entry_id>.g5_frozen_live_parity`.
- Public `sensor.doems_g5_frozen_live_parity`.
- Diagnostic `button.doems_g5_capture_frozen_live_parity`.
- Deterministic SHA-256 fingerprint of the complete frozen snapshot.
- Compact pass/mismatch/blocked result with exact_match, difference_count, blockers, difference paths and decision summaries.
- Snapshot includes native 288-slot input, 72 transport rows, time contract, SOC, EMS settings, profile and Scheduler/Plan Store surface.
- Regression tests for exact match, fingerprint stability, fail-closed incomplete input, mismatch reporting and non-actuation.

## G5 comparison
The frozen snapshot is evaluated through:
1. direct calls to the vendored/pinned Alpha76 Energy Need -> Planner Preview -> Plan72 decision functions;
2. the production DOEMS 288x15m -> Alpha41 72x60m adapter path into those same frozen decision functions.

The resulting Plan72 outputs are also translated through the current read-only DOEMS Bridge comparator using the same frozen Scheduler/Plan Store surface.

Expected live acceptance:
- status=pass
- exact_match=true
- difference_count=0
- blockers=[]

## Hard safety boundary
G5 is diagnostic only:
- no Plan Store mutation by capture;
- no Scheduler/Safety/Execution write;
- no Home Assistant control service call;
- no mode switch;
- no direction write;
- no power-setpoint write;
- service_calls_performed=false;
- physical_execution_authority=false;
- cutover_permitted=false.

`anker_ems` remains the physical battery authority.

## Next gate
After installation, run exactly one live G5 capture while DOEMS EMS is ready. A passing capture can close Step 13 G5. Step 14 G6 remains closed until the project route explicitly opens it; Step 12.7 still requires its own natural live execution-shadow lifecycle evidence.
