# DOEMS 0.2.0-alpha.2 - Battery Input Contract

## Purpose

This release implements R1 of the reset route: a read-only battery observation/input contract on top of the clean 0.2.0-alpha.1 forecast baseline.

It does not add Plan Store, Scheduler, automatic planning, Safety, execution or physical battery control.

## Added

- Optional Battery Observation toggle in DOEMS Options.
- Configurable Home Assistant sources for:
  - battery SOC;
  - battery capacity;
  - battery charge power;
  - battery discharge power;
  - battery device status.
- Read-only runtime contract with fail-closed validation.
- New public entity:
  - `sensor.doems_battery_input_status`
- Published contract attributes include:
  - status;
  - ready_for_soc_projection;
  - soc_percent;
  - capacity_kwh;
  - charge_power_w;
  - discharge_power_w;
  - device_status;
  - direction consistency;
  - blockers and warnings;
  - exact source entities;
  - capacity source provenance.

## Battery-capacity policy

The configured live battery-capacity sensor is authoritative for future SOC projection. There is no silent fallback to the former fixed 7.2 kWh value.

If SOC or capacity is unavailable, invalid or uses an unsupported unit, the contract blocks fail-closed.

## Direction validation

Charge and discharge power are read independently. Simultaneous positive charge and discharge is treated as a source inconsistency and blocks the contract.

Device-status versus power-direction mismatch is surfaced as a warning because source updates can arrive at slightly different moments.

## Safety boundary

This release is strictly read-only.

- no battery service calls;
- no mode switching;
- no power setpoints;
- no Plan Store;
- no Scheduler;
- no physical execution authority.

`physical_execution_authority=false` remains mandatory.

## Preserved architecture

- Energy Forecast unchanged;
- Solar Forecast unchanged;
- Prices Forecast unchanged;
- native 15-minute / 72-hour / 288-slot forecast architecture unchanged.

## Validation

- Python compile;
- full pytest suite;
- dedicated R1 battery-contract regression tests;
- JSON validation;
- release archive verification.
