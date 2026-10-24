# DOEMS 0.2.0-alpha.3 - Manual Plan Store

## Purpose

This release implements R2 of the reset route: the persistent manual Plan Store, after R1 Battery Input Contract was proven live green.

It restores the hand-operated planning layer before any automatic planning, SOC replanning, Scheduler, Safety or physical execution is added.

## Added

- Three independent persistent manual plan slots.
- Editable per-slot fields:
  - action: geen / laden / ontladen;
  - execution mode: direct / gepland;
  - start time;
  - power;
  - target SOC;
  - maximum runtime;
  - maximum start delay.
- Proven manual input ranges:
  - power: 100-3500 W, step 100 W;
  - target SOC: 5-100%, step 1%;
  - maximum runtime: 0.5-12 h, step 0.5 h;
  - maximum start delay: 1-120 min, step 1 min.
- Restart-persistent Home Assistant storage under a new reset-line manual-only storage key.
- Public plan entities reuse the existing DOEMS entity identities:
  - select.doems_plan_1_action etc.;
  - select.doems_plan_1_execution_mode etc.;
  - number.doems_plan_1_power etc.;
  - datetime.doems_plan_1_start_time etc.;
  - sensor.doems_plan_1_status etc.
- Manual-only services:
  - doems.schedule_plan;
  - doems.cancel_plan;
  - doems.clear_plan.

## Lifecycle scope

R2 supports:
- editing -> concept;
- schedule -> pending;
- cancel -> geannuleerd;
- clear -> clean empty slot.

Terminal completion/expiry handling, automatic cleanup and Scheduler-driven lifecycle belong to later reset stages and are not activated here.

## Historical parity

The manual ranges and three-slot concept are grounded in the proven July manual battery-control package and the later persistent Anker EMS Plan Store. The public DOEMS entity identities are reused to avoid duplicate `_2` entities when old registry entries are present.

## Safety boundary

This release is storage and validation only.

- no SOC projection yet;
- no automatic planner;
- no Scheduler;
- no Safety or Prestart;
- no battery mode switch;
- no power setpoint;
- no physical service call;
- physical_execution_authority=false.

R1 Battery Input Contract remains read-only and unchanged.

## Preserved forecast architecture

Energy, Solar and Prices remain unchanged on the native 15-minute / 72-hour / 288-slot forecast architecture.

## Validation

- Python compile;
- full pytest suite;
- pure manual-plan validation/status regressions;
- public entity identity regression;
- manual-only/no-execution regression;
- JSON validation;
- release archive verification.

## Live exit gate

R2 is green only after Home Assistant proves:
1. all three plan slots are available without duplicate entity IDs;
2. one plan can be edited and scheduled;
3. a different slot remains unchanged;
4. the plan survives a Home Assistant restart;
5. cancel and clear work predictably;
6. no Scheduler/automatic planning/physical execution appears.
