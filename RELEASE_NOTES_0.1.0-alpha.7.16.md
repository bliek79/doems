# DOEMS 0.1.0-alpha.7.16 - G6 Step 5A Live SOC Shadow Runtime

## Scope

Alpha7.16 activates the copied Alpha76 decision chain inside the DOEMS Home Assistant runtime for the first time, still fully shadow-only.

The existing DOEMS Energy, Solar and Prices forecasts remain the only forecast input. The proven Alpha41 288 native quarter -> 72 rolling 60-minute compatibility contract remains unchanged. A generic Home Assistant SOC percentage sensor can now be selected as a read-only EMS input.

No battery action is executed.

## Added

- Optional generic `soc_entity` in EMS Options.
  - sensor domain only;
  - percentage unit required;
  - DOEMS output entities cannot be selected as their own input;
  - the source is read-only;
  - unavailable state is accepted at configuration time and handled fail-closed at runtime.
- `ems_soc.py`
  - pure 0..100 SOC parser;
  - invalid, unknown, unavailable and out-of-range values return no usable SOC.
- `ems_shadow_runtime.py`
  - listens to the configured SOC source;
  - listens to existing DOEMS Energy, Solar and Prices runtime updates;
  - coalesces update triggers;
  - assembles the already-published Alpha7.15 live forecast input;
  - invokes the frozen Alpha76 Energy Need -> Planner Preview -> Plan72 shadow chain;
  - exposes compact diagnostics only.
- `sensor.doems_ems_shadow`
  - runtime status;
  - SOC source/status/value;
  - input contract status;
  - native valid slot count and transport row count;
  - Energy Need status;
  - Planner Preview decision;
  - Plan72 status/count and SOC summary;
  - explicit non-actuating safety flags.

## Fail-closed runtime states

The shadow runtime does not calculate through missing prerequisites. It reports:
- waiting_for_soc_source
- waiting_for_valid_soc
- waiting_for_forecast_components
- waiting_for_complete_forecast
- error

Only a valid SOC plus complete 288-slot / 72-row forecast contract can produce `ready`.

## Preserved architecture

- DOEMS Forecast remains native 15 minutes / 72 hours / 288 slots.
- Alpha41 rolling 288 -> 72 compatibility mapping is unchanged.
- No clock-hour rounding is introduced.
- Alpha76 Energy Need / Planner Preview / Plan72 ordering and policy remain the copied parity baseline.
- EMSSettings remain immutable static configuration.
- `startup_delay_seconds` is still read but does not activate a startup gate.

## Safety boundary

The release explicitly keeps:
- startup_delay_runtime_gate_active=false
- plan_store_write=false
- scheduler_invoked=false
- service_calls_performed=false
- physical_execution_authority=false

Not included:
- no Planner Action Bridge runtime
- no Plan Store writes
- no Scheduler
- no Prestart/Safety/Controller/Execution
- no Anker control mapping
- no physical charge/discharge service calls
- no Step 5B

## Step 5A status after Alpha7.16

The live SOC/runtime-invocation layer is built and publishable. Step 5A as a whole is not yet live-green until Home Assistant validates:
- the selected SOC source;
- `sensor.doems_ems_shadow`;
- exact 288 native slots / 72 transport rows;
- live Energy Need / Preview / Plan72 output;
- continued physical_execution_authority=false.

Step 5B remains blocked until this live validation is complete.

## Live validation target

After installing Alpha7.16:
1. Open DOEMS Options -> EMS battery settings and select the same physical SOC percentage sensor used by the legacy EMS.
2. Reload/restart DOEMS.
3. Confirm `sensor.doems_ems_shadow` exists.
4. Confirm the sensor progresses from a fail-closed waiting state to `ready` only when SOC and all forecast inputs are valid.
5. Confirm `soc_source_entity` and `soc_percent` match the selected source.
6. Confirm `native_valid_slot_count=288` and `transport_row_count=72`.
7. Confirm Energy Need, Planner Preview and Plan72 diagnostics are populated.
8. Confirm startup_delay_runtime_gate_active=false, plan_store_write=false, scheduler_invoked=false, service_calls_performed=false and physical_execution_authority=false.
