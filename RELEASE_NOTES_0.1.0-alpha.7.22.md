# DOEMS 0.1.0-alpha.7.22 - G6 Step 5A Final Automatic Execution Shadow

## Scope

Alpha7.22 completes the observer-only Step 5A automatic execution chain.

It adds:
- Alpha76-style two-stage control-path stability;
- 60-second pre-mode / post-mode stability checks;
- the final Automatic Execution Shadow gate;
- central diagnostics in `sensor.doems_ems_shadow`.

The chain is now:

DOEMS Forecast -> 288 native quarters -> 72 Alpha41 rows -> Energy Need -> Planner Preview -> Plan72 -> Bridge -> shadow Plan Store -> Scheduler -> Prestart -> Automatic Safety -> Execution Handoff -> Final Revalidation -> Mode-switch Preview -> Final Automatic Execution Shadow.

## Control-path stability

The existing Alpha7.21 observation contract remains the source mapping.

Alpha7.22 adds temporal stability:
- pre-mode requires the operating-mode entity to be available and unchanged for at least 60 seconds;
- while in self_consumption, direction and power setpoint remain post-mode requirements and do not block pre-mode readiness;
- once operating mode is third_party_control, action direction and power setpoint must both be available and unchanged for at least 60 seconds;
- no mode switch is performed by this release.

## Final Automatic Execution Shadow

The final shadow gate mirrors the frozen Alpha76 technical blockers:
- automatic Scheduler selection;
- Prestart safe;
- Automatic Safety safe;
- Execution Handoff ready;
- Final Revalidation safe;
- Mode-switch Preview ready;
- execution-buffer rule, with the existing safety-charge recovery exception;
- forecast ready;
- configured and stable control path;
- no physical test;
- no existing execution;
- manual override priority;
- trading requires fully known prices.

Possible statuses:
- `idle`: no start-ready automatic action;
- `blocked`: an automatic action is selected but one or more technical blockers remain;
- `ready_disarmed`: every technical observer gate is green.

## Hard Step 5A boundary

Alpha7.22 deliberately has no automatic-execution arm and no physical execution authority.

Hard invariants:
- `auto_shadow_armed=false`;
- `auto_shadow_execution_permitted=false`;
- `auto_shadow_physical_control=false`;
- no `async_run_*` method in the final shadow module;
- no Anker Home Assistant service calls;
- no mode write;
- no direction write;
- no power write;
- `automatic_execution_armed=false`;
- `mode_switch_service_calls_available=false`;
- `service_calls_performed=false`;
- `physical_execution_authority=false`.

Step 5B remains blocked.

## Central validation sensor

`sensor.doems_ems_shadow` now also exposes compact diagnostics for:
- final automatic shadow status;
- technical readiness;
- selected slot/action/purpose/power/target/start;
- blockers and warnings;
- control-path readiness and reason;
- current stable seconds and required stable seconds;
- pre-mode stability;
- post-mode stability.

No full Plan72 array is added to this sensor.

## Live validation

Expected during normal self_consumption, well before an action:
- control-path pre-mode becomes ready after 60 stable seconds;
- final automatic shadow remains `idle` while Scheduler is not start-ready;
- physical boundary flags remain false.

When a start-ready automatic action occurs:
- technical blockers must be visible from the same sensor;
- when every observer gate is green, status may reach `ready_disarmed`;
- physical execution remains impossible.
