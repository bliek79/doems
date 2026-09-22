# DOEMS 0.1.0-alpha.11 - Step 12.2 Action Controller / Execution Handoff

## Scope

Alpha11 builds only **Step 12.2 - Action Controller + automatic execution-handoff**.

The implementation copies the current working Step-12.2 behavior from `dummy-os-anker-ems` while keeping the already migrated DOEMS Forecast, Energy Need, Plan72, Plan Store, Scheduler, Prestart, Safety and Step-12.1 control-path layers authoritative.

## Added

- `custom_components/doems/ems_action_controller.py`
  - source-parity semantic Action Controller for the manual/legacy Scheduler path;
  - prepares desired mode, direction and power only;
  - performs no Home Assistant service calls;
  - publishes `controller_physical_control=false`.

- `custom_components/doems/ems_execution_handoff.py`
  - dedicated automatic Safety -> Execution handoff;
  - automatic Plan72 actions do **not** pass through the legacy Action Controller;
  - preserves the source blockers:
    - `safety_handoff_not_safe`;
    - `prestart_not_safe`;
    - `planner_identity_mismatch`;
    - `planner_identity_missing`;
    - `invalid_action`;
    - `invalid_power`;
    - `invalid_target_soc`;
    - `invalid_runtime`;
    - `control_path_not_configured`;
    - `physical_test_active`;
    - `execution_already_active`;
  - preserves source warnings:
    - `external_mode_switch_required`;
    - `planner_revision_changed`;
  - can reach `ready_observe` but never grants execution permission.

## Runtime wiring

The runtime order is now:

`Plan72 -> Bridge -> Plan Store -> Scheduler -> Prestart -> Automatic Safety -> Execution Handoff`

alongside the separate read-only manual/legacy observer path:

`Scheduler -> legacy Safety evaluation -> Action Controller`

The automatic handoff consumes Safety/Prestart directly and does not consume Action Controller output.

## Physical safety boundary

Alpha11 deliberately does not add:

- Final Revalidation;
- mode-switch transaction;
- Execution Controller;
- automatic execution arm switch;
- operating-mode writes;
- direction writes;
- power-setpoint writes;
- Home Assistant battery service calls;
- physical execution authority.

The runtime must continue to publish:

- `execution_controller_invoked=false`;
- `automatic_execution_armed=false`;
- `service_calls_performed=false`;
- `physical_execution_authority=false`.

`action_controller_invoked` may now be true because the read-only evaluator exists.

## Validation

CI must pass:

- Python compile;
- full pytest suite;
- JSON validation;
- Alpha11 release-contract validation;
- Foundation Regression CI.

After installation, Alpha11 is intended for live shadow validation of Step 12.2 only. Step 12.3 remains closed.
