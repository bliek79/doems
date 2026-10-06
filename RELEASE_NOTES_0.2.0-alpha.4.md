# DOEMS 0.2.0-alpha.4 - Manual SOC Replanning

## Purpose

This release implements R3 of the reset route: restore the proven manual-planning effect on the future SOC line before any automatic planner, Scheduler, Safety or physical execution is reintroduced.

R0 Forecast Reset Baseline, R1 Battery Input Contract and R2 Manual Plan Store were all proven live green before this build.

## Historical parity basis

The July manual battery-control implementation is the functional reference for this step:

- accepted manual plans act as hard future commitments;
- a manual charge/discharge action changes projected SOC from its own time window;
- all later SOC values are recalculated from that changed SOC;
- later PV surplus can be used again when a previous manual discharge created battery headroom;
- manual energy is bounded by requested power, overlap duration and target SOC.

The reset implementation translates this behavior to the native DOEMS 15-minute / 72-hour / 288-slot time axis.

## Added

- Native manual SOC projection runtime:
  - `manual_soc_projection_model.py`
  - `manual_soc_projection.py`
- Canonical public status sensor:
  - `sensor.doems_manual_soc_projection`
- Native 288-point SOC timeline:
  - `sensor.doems_manual_soc_projection_timeline`
- Restored dashboard compatibility identity:
  - `sensor.doems_ems_plan72_hours`

## Projection contract

Inputs:
- current SOC from the R1 Battery Input Contract;
- current live battery capacity from the R1 Battery Input Contract;
- native Energy Forecast quarters;
- native Solar Forecast quarters;
- optional Prices timeline metadata;
- R2 manual plans with `origin=manual` and lifecycle `pending` or `actief`.

Rules:
- exact 288 contiguous 15-minute slots over 72 hours;
- forecast-axis mismatch blocks fail-closed;
- overlapping active manual plans block fail-closed;
- technical SOC floor: 5%;
- maximum SOC: 100%;
- charge efficiency: 92%;
- discharge efficiency: 92%;
- projection power ceiling: 3500 W;
- manual energy = requested power x actual time overlap;
- charge stops at target SOC / 100%;
- discharge stops at target SOC / 5%;
- manual time has priority over baseline self-consumption flows;
- later quarters continue sequentially from the changed SOC.

## Baseline flow between manual actions

R3 does not introduce an automatic economic planner. Outside manual time windows the SOC projection only applies the physical self-consumption baseline implied by the existing Energy + Solar forecasts:

- solar serves expected home demand first;
- remaining solar may charge the battery;
- remaining home deficit may discharge the battery;
- remaining deficit/import or solar/export is diagnostic only.

This gives the manual plan a meaningful future SOC context without adding safety/trade policy.

## Compatibility surface

`sensor.doems_ems_plan72_hours` reuses the former DOEMS Plan72 Hours identity so the existing planning dashboard can consume the restored SOC line.

Its `plan` attribute is an hourly presentation derived from the native quarter series. A quarter-offset 72-hour window may span 73 clock-hour buckets because the first and last clock hours can be partial. The authoritative calculation remains exactly 288 native quarters.

R3 deliberately does not invent reserve, safety-charge, trade-charge, trade-discharge or execution-reserve values. Those series stay absent until their own reset stages are restored.

## Safety boundary

This release is still observer/shadow planning only.

- no automatic planner;
- no automatic Plan Store writes;
- no Scheduler;
- no Safety or Prestart;
- no mode switch;
- no power setpoint;
- no Home Assistant battery service calls;
- `physical_execution_authority=false`.

## Validation

- Python compile;
- full pytest suite;
- exact 288-slot / 72-hour contract;
- manual charge timing + target-SOC clamp;
- manual discharge target/minimum clamp;
- cancelled/concept/cleared plans ignored;
- later solar reuse after manual discharge;
- partial first/last hour compatibility aggregation;
- time-axis mismatch fail-closed;
- overlapping manual plans fail-closed;
- 92% / 92% efficiency and 5% minimum regression;
- read-only/no-execution regression;
- JSON validation;
- release archive verification.

## Live exit gate

R3 is green only after Home Assistant proves:

1. `sensor.doems_manual_soc_projection` is `ready`, with 288 native slots and no blockers.
2. With no pending manual plan, a stable baseline SOC line is available.
3. Scheduling a future manual charge changes the SOC line immediately at the planned time, before any physical action occurs.
4. Cancelling/clearing that plan removes its projected effect immediately.
5. A manual discharge changes the line symmetrically and never projects below target SOC or 5%.
6. The same pending plan and projection survive a Home Assistant restart.
7. Energy, Solar, Prices and R1 Battery Input remain healthy.
8. Scheduler and physical execution remain absent.
