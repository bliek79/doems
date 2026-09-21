# DOEMS 0.1.0-alpha.8 - EMS Plans Foundation

## Scope

Alpha8 restarts the DOEMS EMS build from the clean `0.1.0-alpha.7.15` architecture baseline.

The target is again the original architecture:

`Dummy OS Data forecasts -> standalone DOEMS EMS -> later one-time cutover -> retire anker_ems`

Alpha8 adds the first definitive standalone EMS planning components inside DOEMS. It does not add physical battery execution.

## Architecture

The forecast contract remains frozen:

`288 x 15 minutes -> deterministic 72 x 60 minutes -> copied EMS decision core`

The Alpha8 planning chain is:

`Energy Need -> Planner Preview -> Plan72 -> DOEMSPlannerBridge -> DOEMSPlanStore -> DOEMSScheduler`

The proven rolling 76-hour Prices buffer fix is carried forward so the exact 288-quarter EMS window remains complete across quarter rolls.

## Added

- `DOEMSPlanStore`
  - exactly three persistent plan slots;
  - definitive storage namespace `doems.<entry_id>.plans`;
  - manual ownership protection;
  - planner identity and revision metadata;
  - automatic-plan lifecycle reconciliation.
- `DOEMSScheduler`
  - deterministic three-slot evaluation;
  - scheduled actions before direct actions;
  - oldest due scheduled action first;
  - lowest slot as final tie-break;
  - direction-specific power validation;
  - configured technical minimum and maximum SOC validation;
  - no physical execution.
- `DOEMSPlannerBridge`
  - converts valid Plan72 grid actions into at most three DOEMS plans;
  - preserves manual slot priority;
  - uses configured charge/discharge power and SOC bounds.
- `DOEMSEMSRuntime`
  - owns Plan Store and Scheduler;
  - automatic planning requires valid SOC and complete 288/288 forecast input;
  - manual Scheduler state remains available even when automatic planner prerequisites are missing;
  - execution mode is `validation`.
- Definitive Home Assistant plan entities for Plan 1, 2 and 3:
  - action;
  - execution mode;
  - start time;
  - power;
  - target SOC;
  - maximum runtime;
  - maximum start delay;
  - plan status.
- Central `sensor.doems_scheduler`.
- Central `sensor.doems_ems`.
- Optional read-only SOC source in EMS Options.

## Manual priority

Any user edit immediately sets the slot origin to `manual` and clears planner-owned identity metadata.

The automatic planner may not overwrite an active/manual plan slot.

## Superseded development path

DOEMS Alpha7.16 through Alpha7.25 remain historical reference material only. Their proven fixes may be carried forward selectively, but their temporary `shadow_*` and `legacy_*` architecture is not the Alpha8 target.

Alpha8 introduces no runtime dependency on `anker_ems`.

## Safety boundary

Alpha8 is non-actuating:

- `automatic_execution_armed=false`
- `service_calls_performed=false`
- `physical_execution_authority=false`
- no battery operating-mode write;
- no charge/discharge direction write;
- no battery power write;
- no authority-transfer mechanism.

The only Home Assistant service call retained in DOEMS is the pre-existing optional EnergyZero gas-price data action; it is unrelated to battery control.

## Live validation target

After installation:

1. Confirm `sensor.doems_ems`, `sensor.doems_scheduler` and all three plan-slot entity groups exist.
2. Configure the battery SOC source in DOEMS EMS Options.
3. Confirm a manually edited plan persists across reload/restart and reports `origin=manual`.
4. Confirm Scheduler status follows future/due/expired timing without changing the battery.
5. Confirm automatic Plan72 actions may occupy only available planner-safe slots.
6. Confirm incomplete forecast input blocks new automatic plan writes.
7. Confirm all physical-execution flags remain false.
