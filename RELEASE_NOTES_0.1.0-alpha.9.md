# DOEMS 0.1.0-alpha.9 - Safety / Prestart

## Scope

Alpha9 adds **Step 11 - Safety / Prestart** to the standalone DOEMS EMS chain.

The implementation copies the current working behavior from the existing EMS source into DOEMS itself. There is no runtime dependency on the source integration.

The chain is now:

`Plan72 -> Planner Bridge -> DOEMS Plan Store -> DOEMS Scheduler -> Prestart Validator -> Automatic Safety Guard`

The copy stops there. **Controller / Execution remains Step 12 and is not part of this release.**

## Added

- `custom_components/doems/ems_prestart_validator.py`
  - continuous early diagnostics for the nearest automatic pending plan;
  - authoritative validation when the Scheduler selects an automatic start-ready plan;
  - planner identity continuity check;
  - planner revision/signature warning;
  - live SOC direction checks close to start;
  - execution-reserve protection for discharge;
  - explicit early / near_start / due diagnostic phases.

- `custom_components/doems/ems_safety_guard.py`
  - automatic Scheduler -> Safety handoff;
  - rechecks Prestart, planner identity, bridge validity, forecast readiness and execution buffer;
  - validates action, power, SOC and target SOC;
  - detects conflicting simultaneous charge/discharge observation;
  - preserves the source blocker `control_path_not_configured` until Step 12 exists.

- DOEMS runtime wiring after the definitive Scheduler.
- Step 11 diagnostic fields on `sensor.doems_ems`.
- regression tests for the copied blockers and the Step-12 safety boundary.

## Important Step-12 boundary

Alpha9 deliberately does **not** add:

- Controller / Execution;
- `start_plan_now`;
- battery operating-mode writes;
- action-direction writes;
- power-setpoint writes;
- Home Assistant physical service calls;
- physical execution authority.

Until Step 12 is built, DOEMS explicitly supplies:

- `control_path_configured=false`;
- `physical_test_active=false`;
- `execution_active=false`.

Therefore an automatic start-ready plan may pass Prestart but the automatic Safety handoff must still block on `control_path_not_configured`. That is the expected Alpha9 behavior, not a defect.

## Safety invariants

The release keeps:

- native 15-minute / 72-hour / 288-slot forecast architecture;
- the existing three-slot DOEMS Plan Store;
- manual-plan priority;
- Scheduler ownership of timing selection;
- `automatic_execution_armed=false`;
- `service_calls_performed=false`;
- `physical_execution_authority=false`.

## CI before publication

The Step 11 branch passed:

- Python compile;
- full pytest suite: **90 passed**;
- JSON validation;
- existing release-contract validation;
- Foundation Regression CI.

## Live validation after installation

After installing Alpha9 and restarting Home Assistant:

1. Confirm `sensor.doems_ems` reports:
   - `prestart_validator_invoked=true`;
   - `safety_guard_invoked=true`;
   - `action_controller_invoked=false`;
   - `execution_controller_invoked=false`;
   - `physical_execution_authority=false`.

2. With no automatic Scheduler-ready plan, confirm Prestart is `not_required` and Safety is not required.

3. When an automatic pending plan approaches its start:
   - inspect `prestart_diagnostic_phase`;
   - inspect `prestart_diagnostic_minutes_to_start`;
   - inspect blockers/warnings and planner identity/signature continuity.

4. When the Scheduler actually selects an automatic start-ready plan:
   - Prestart may become safe when all current conditions pass;
   - Safety handoff should still be blocked by `control_path_not_configured` because Step 12 is intentionally absent.

5. Confirm no battery operating mode, direction or power setpoint changes occur.

This release is intended for live validation of Step 11 only. Step 12 remains closed.
