# DOEMS 0.1.0-alpha.7.21 - G6 Step 5A Control-path Observation Contract

## Scope

Alpha7.21 keeps the complete Alpha7.20 downstream shadow chain unchanged and adds one central read-only observation-completeness contract to `sensor.doems_ems_shadow`.

The purpose is operational validation from one sensor: the user can see exactly which downstream battery observation source is configured, available, valid, missing or unavailable before Prestart / Safety / Execution shadow gates become authoritative.

## Central observation contract

The six existing optional read-only EMS sources are diagnosed individually:
- device status;
- battery charge power;
- battery discharge power;
- operating mode;
- action direction;
- power setpoint.

For each source the shadow sensor exposes:
- configured;
- available;
- valid;
- status;
- entity_id;
- current normalized value.

Aggregate diagnostics expose:
- observation contract status;
- expected source count;
- configured source count;
- valid source count;
- missing sources;
- unavailable sources;
- invalid sources.

No entity IDs are hardcoded or guessed. The existing EMS Options remain the authoritative mapping.

## Two-stage control-path readiness

The contract mirrors the Alpha76 control-path model:
- pre-mode readiness requires a valid operating-mode observation;
- post-mode controls are required only when operating mode is `third_party_control`;
- post-mode readiness requires valid action-direction and power-setpoint observations.

This is diagnostic/read-only only. It does not switch mode or write controls.

## Preserved chain

Forecast -> 288 native quarters -> 72 Alpha41 rows -> Energy Need -> Planner Preview -> Plan72 -> Bridge -> shadow Plan Store -> Scheduler -> Prestart -> Automatic Safety -> Execution Handoff -> Final Revalidation -> Mode-switch Preview.

No planner, safety or execution decision semantics change.

## Hard physical boundary

Unchanged:
- no automatic execution arm;
- no physical Execution Controller state machine;
- no `async_run_*` route;
- no Home Assistant service call from the shadow runtime;
- no operating-mode write;
- no direction write;
- no power write;
- `automatic_execution_armed=false`;
- `mode_switch_service_calls_available=false`;
- `service_calls_performed=false`;
- `physical_execution_authority=false`.

Step 5B remains blocked.

## Live validation

After installing Alpha7.21, only `sensor.doems_ems_shadow` is required for Step 5A validation.

Expected before the six observation sources are configured:
- `shadow_observation_contract_status=not_configured` or `partial`;
- missing source names are explicit;
- downstream gates remain fail-closed where these sources become required.

After mapping valid sources:
- configured and valid counts increase deterministically;
- pre-mode readiness becomes true once operating mode is valid;
- post-mode readiness reflects direction + setpoint availability;
- all physical boundary fields remain false.
