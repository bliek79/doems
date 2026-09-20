# DOEMS 0.1.0-alpha.7.15 - G6 Step 5A Consumer Wiring Part 1

## Scope

Alpha7.15 publishes the first controlled consumer-wiring layer after the live-green Alpha7.14 EMSSettings config-read layer.

The existing DOEMS Forecast remains the source of truth at native 15-minute / 72-hour / 288-slot resolution. A thin Alpha41 compatibility contract groups those 288 native quarters into exactly 72 rolling 60-minute transport rows for the copied Alpha76 EMS decision core.

This release remains shadow-only. It does not activate planner runtime execution, Plan Store writes, Scheduler, battery control or Home Assistant service calls.

## Added

- `ems_input_contract.py`
  - exact 288 native slots -> 72 rolling transport rows;
  - no clock-hour rounding;
  - :00/:15/:30/:45 starts are preserved;
  - four quarters per transport row;
  - Home and Solar energy are summed;
  - import/export prices are averaged;
  - missing native quarters make the corresponding transport row incomplete.
- `ems_live_input.py`
  - consumes the existing DOEMS Energy Forecast, Solar Forecast and Prices runtime;
  - no separate or legacy forecast source is introduced.
- copied frozen Alpha76 decision modules for:
  - Energy Need;
  - Planner Preview;
  - Plan72.
- `ems_alpha76_adapter.py`
  - passes the proven 72-row compatibility view to the copied Alpha76 decision functions;
  - consumes the immutable EMSSettings snapshot as explicit function inputs.

## Settings consumer wiring

Part 1 wires the static settings that belong to the copied decision functions:
- battery_capacity_kwh
- technical_min_soc_percent
- max_soc_percent
- max_charge_power_w
- max_discharge_power_w
- software_reserve_percent
- charge_efficiency_percent
- discharge_efficiency_percent
- minimum_trade_margin_eur_per_kwh

`startup_delay_seconds` remains read-only and intentionally has no runtime gate consumer yet.

The frozen execution buffer remains 2.0 percentage points and is not converted into an Option.

## Preserved Alpha41 time semantics

The compatibility window starts at the shared exact quarter boundary and never rounds :15/:30/:45 back to the clock hour.

The older current-hour-fraction/context-slot interpretation is not used for DOEMS G6.

The Alpha76 decision core remains hourly internally; it is not rewritten into 288 independent quarter decisions.

## Safety boundary

- planner_runtime_active=false
- startup_delay_runtime_gate_active=false
- plan_store_write=false
- scheduler_invoked=false
- service_calls_performed=false
- physical_execution_authority=false
- no Anker source mapping
- no SOC source mapping
- no physical battery control

## Step 5A status after Alpha7.15

- Config-read layer: live green.
- 288 -> 72 Alpha41 compatibility contract: built.
- Existing DOEMS Forecast -> EMS input assembly: built.
- Alpha76 Energy Need / Preview / Plan72 decision core: copied and settings-consumer-ready.
- Live SOC/runtime invocation wiring: still open.
- Step 5A as a whole: not yet green.
- Step 5B: still blocked.

## Validation target

CI proves:
- exact 288 -> 72 grouping;
- quarter-offset starts are preserved;
- one missing native quarter only invalidates its corresponding transport row;
- existing DOEMS Energy/Solar/Prices are the declared live sources;
- all nine decision-relevant static settings are explicit consumers;
- startup_delay remains inactive;
- no plan-store, scheduler, service-call or physical authority is activated.
