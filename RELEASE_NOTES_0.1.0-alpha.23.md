# DOEMS 0.1.0-alpha.23 - Execution Naming Cleanup

## Purpose

Alpha23 cleans up the execution terminology in the DOEMS EMS runtime without
changing planner policy, safety behavior or physical authority.

The previous implementation used terminology that described the current
non-actuating validation mode as part of permanent execution field names.
That wording is removed from the active DOEMS contract. The execution model
remains non-actuating and `physical_execution_authority=false`.

## Public contract changes

The central `sensor.doems_ems` keeps the same entity ID. Its execution
attributes now use neutral names:

- `execution_status`
- `execution_active`
- `execution_reason`
- `execution_identity`
- `execution_slot`
- `execution_action`
- `execution_purpose`
- `execution_requested_power_w`
- `execution_target_soc`
- `execution_max_runtime_h`
- `execution_planned_start_time`
- `execution_planned_end_time`
- `execution_planned_energy_kwh`
- `execution_start_soc`
- `execution_expected_mode`
- `execution_expected_direction`
- `execution_transaction`
- `execution_trace`
- `execution_run_history`
- `execution_recovery_*`
- `execution_persistence_schema_version`
- `execution_store_*`

Terminal execution values are neutral:

- `armed`
- `starting`
- `running`
- `completed`
- `emergency_stopped`
- `recovered_interrupted`

The runtime monitor trigger is now `execution_monitor`.

## Internal cleanup

- `ems_execution.py` is the active execution module.
- `DOEMSExecutionController` is the active controller class.
- Runtime objects, timers, persistence diagnostics and store naming use the
  neutral `execution` contract.
- The previous persistence store is migrated once into the neutral execution
  store and then removed, preserving audit/restart evidence across upgrade.
- Active integration code contains no legacy execution terminology.

## Safety and behavior unchanged

- no Home Assistant control service call is added;
- no mode switch is performed;
- no direction or power setpoint is written;
- safe return remains a preview only;
- automatic arm still starts OFF after setup/reload;
- `physical_execution_authority=false` remains unchanged;
- Step 14 / G6 remains closed;
- Alpha20 planner policy remains unchanged;
- native architecture remains 15 minutes / 72 hours / 288 slots.

## Validation automation impact

The existing Home Assistant automation `DOEMS EMS Execution` must read the
new neutral `execution_status`, `execution_active` and `execution_reason`
attributes and accept the neutral terminal result values. The Google Sheets
tab and visible column names remain unchanged.

## Regression coverage

Alpha23 adds an explicit active-integration naming gate plus the existing
Step 12.5, Step 12.6, recorder budget, multi-rate, safety and G5 regression
coverage updated to the neutral execution contract.

Live acceptance after installation:

1. verify `sensor.doems_ems` exposes the neutral execution attributes;
2. verify the old execution attribute family is absent;
3. verify `physical_execution_authority=false`;
4. let `DOEMS EMS Plan & Decision` continue writing normally;
5. after the next natural automatic execution lifecycle, verify exactly one
   row is written to `DOEMS EMS Execution` with the neutral result values.
