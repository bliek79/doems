# DOEMS 0.1.0-alpha.7.20 - G6 Step 5A Downstream Shadow Parity

## Scope

Alpha7.20 extends the live-green Alpha7.19 chain through the remaining non-actuating Alpha76 downstream gates:

DOEMS Forecast -> 288 native quarters -> 72 Alpha41 compatibility rows -> Energy Need -> Planner Preview -> Plan72 -> Planner Action Bridge -> shadow Plan Store -> Scheduler -> Prestart Validator -> Automatic Safety Guard -> Execution Handoff -> Final Revalidation -> Mode-switch Preview.

The legacy Safety Guard / Action Controller path is also retained as a diagnostic parity layer.

## Added

- Frozen Alpha76 Prestart Validator.
- Frozen Alpha76 Safety Guard, including the automatic Scheduler -> Safety handoff.
- Frozen Alpha76 Action Controller as command-preview only.
- Isolated `execution_shadow.py` containing only:
  - automatic Safety -> Execution handoff evaluation;
  - final live revalidation;
  - guarded mode-switch transaction preview.
- No physical Execution Controller state machine is included.
- Optional read-only EMS observation sources:
  - device status sensor;
  - battery charge-power sensor;
  - battery discharge-power sensor;
  - operating-mode select;
  - action-direction select;
  - power-setpoint number.
- Changes to any configured observation source trigger a shadow refresh.
- Compact downstream diagnostics are exposed through `sensor.doems_ems_shadow`.

## Preserved Alpha76 gate semantics

Prestart keeps:
- planner/forecast/bridge validity;
- execution-buffer logic with safety-charge recovery exception;
- stable planner identity and revision-signature diagnostics;
- action/power/SOC/target validation;
- live target-direction validation;
- discharge execution-reserve protection;
- early vs near-start/due decision-window behavior.

Automatic Safety Guard keeps:
- authoritative Prestart dependency;
- planner identity;
- forecast/bridge/buffer checks;
- control-path configuration;
- live SOC/target and power-conflict checks;
- physical-test / execution-busy blockers.

Execution shadow keeps:
- Safety -> Execution handoff prerequisites;
- final live revalidation;
- planner identity/signature recheck;
- SOC, target, reserve and power recheck;
- mode-switch transaction preview with zero-power guard and safe-return steps.

## Hard physical boundary

Alpha7.20 deliberately does not include or expose any physical automatic execution route:

- no `async_run_*` method in `execution_shadow.py`;
- no `hass.services.async_call` in the shadow runtime or downstream copied gates;
- `physical_test_active=false`;
- `execution_active=false`;
- `simulation_mode=true`;
- `automatic_execution_armed=false`;
- `mode_switch_service_calls_available=false`;
- `service_calls_performed=false`;
- `physical_execution_authority=false`.

No operating-mode change, direction write or non-zero power write is possible in this release.

## Existing contracts unchanged

- native forecast: 15 minutes / 72 hours / 288 slots;
- Prices buffer: 76 hours / 304 slots;
- Alpha41 288 -> 72 compatibility mapping;
- Alpha7.19 rolling price-window fix;
- three-slot shadow Plan Store;
- Scheduler semantics;
- Step 5B remains blocked.

## Live validation

After installation, configure any available read-only downstream observation entities in EMS Options.

Expected:
- upstream remains `ready`, 288/288, 72 transport rows;
- Prestart diagnostic populates even before Scheduler-ready time;
- authoritative Prestart activates only when Scheduler selects a start-ready automatic plan;
- Safety/Execution/Final-Revalidation gates either pass or return explicit blockers;
- missing optional control-path observations must block downstream readiness rather than being guessed;
- mode-switch preview remains non-actuating;
- every physical boundary flag remains false.
