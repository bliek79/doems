# DOEMS 0.1.0-alpha.7.17 - G6 Step 5A Shadow Bridge Plan Store Scheduler

## Scope

Alpha7.17 extends the live-green Alpha7.16 shadow planner with the next copied Alpha76 stages:

DOEMS Forecast -> Alpha41 288-to-72 compatibility view -> Alpha76 Energy Need -> Planner Preview -> Plan72 -> Planner Action Bridge -> persistent shadow Plan Store -> Scheduler.

The chain remains non-actuating. No Prestart Validator, Safety Guard, Action Controller or Execution Controller is invoked and no battery service is called.

## Added

- Frozen Alpha76 `planner_action_bridge.py`
  - exact forced-action segmentation;
  - safety/trade purpose semantics;
  - 0.10 kWh actionable safety threshold;
  - 2-minute handoff allowance;
  - 10 W upward power rounding;
  - target SOC derived from explicit grid action energy;
  - stable planner identity and revision signature;
  - three-slot preview and manual-slot protection.
- Frozen Alpha76 `plan_store.py`
  - exactly three persistent slots;
  - ownership and lifecycle semantics;
  - manual edit protection;
  - automatic concept/pending reconciliation;
  - automatic stale-slot cleanup;
  - isolated DOEMS storage namespace: `doems.<entry_id>.shadow_plans`.
- Frozen Alpha76 `scheduler.py`
  - validation of action, power, target SOC, runtime and delay;
  - scheduled actions before direct actions;
  - oldest due action first;
  - lowest slot as final tie-break;
  - no physical control.
- Live shadow runtime orchestration mirrors the frozen sequence:
  1. Scheduler pre-clean evaluation
  2. expired automatic-plan release
  3. Scheduler snapshot
  4. Planner Action Bridge
  5. controlled shadow Plan Store sync
  6. signature-protected Scheduler handoff
  7. Scheduler refresh
  8. Bridge refresh
- Compact diagnostics in `sensor.doems_ems_shadow` for:
  - Bridge status and candidate count;
  - shadow Plan Store write gate and changed/written/cleared slots;
  - Scheduler status and selected shadow slot/action;
  - compact slot 1/2/3 summaries.

## Preserved upstream contract

- existing DOEMS Forecast remains the only forecast source;
- native contract remains 15 minutes / 72 hours / 288 slots;
- proven Alpha41 compatibility mapping remains 288 -> 72 rolling 60-minute blocks;
- copied Alpha76 Energy Need / Planner Preview / Plan72 behavior remains upstream;
- SOC remains read-only from the configured Home Assistant percentage sensor.

## Safety boundary

This release explicitly keeps:
- startup_delay_runtime_gate_active=false
- prestart_validator_invoked=false
- safety_guard_invoked=false
- action_controller_invoked=false
- execution_controller_invoked=false
- service_calls_performed=false
- physical_execution_authority=false

The shadow Plan Store and Scheduler are active only to reproduce persistent plan lifecycle and scheduling decisions. They have no physical execution path.

## Step 5A status after Alpha7.17

The Bridge / shadow Plan Store / Scheduler stage is built and publishable after green CI. Step 5A as a whole remains pending live Home Assistant validation of the new bridge/store/scheduler diagnostics.

Step 5B remains blocked.

## Live validation target

After installing Alpha7.17, validate `sensor.doems_ems_shadow`:
- state remains `ready`;
- Bridge status is populated;
- shadow Plan Store namespace is `doems.<entry_id>.shadow_plans`;
- exactly three shadow slots are visible;
- Scheduler status is populated;
- any selected slot/action is shadow-only;
- Prestart, Safety, Controller and Execution remain not invoked;
- service_calls_performed=false;
- physical_execution_authority=false.
