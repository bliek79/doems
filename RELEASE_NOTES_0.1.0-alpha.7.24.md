# DOEMS 0.1.0-alpha.7.24 - G6 Step 5B Disarmed Execution Authority Preparation

## Scope

Alpha7.24 builds Step 5B exactly as designed: a fully disarmed execution-authority preparation layer behind the live-green Step 5A chain.

It adds:
- immutable execution-envelope capture;
- deterministic envelope fingerprinting;
- non-actuating transaction rehearsal;
- fail-closed change detection after capture;
- compact Step 5B diagnostics on sensor.doems_ems_shadow.

## Entry gate

An envelope is created only when the complete Step 5A observer chain is green and the final shadow status is ready_disarmed.

The gate also requires:
- automatic planner origin;
- valid planner identity and signature;
- Scheduler start-ready;
- Prestart safe;
- Automatic Safety safe;
- Execution Handoff ready;
- Final Revalidation safe;
- Mode-switch Preview ready;
- configured and stable control path;
- valid action, power, target SOC and runtime;
- no manual override;
- no physical test;
- no DOEMS execution;
- complete forecast;
- known prices for trading actions.

## Immutable execution envelope

The read-only snapshot contains:
- slot;
- planner identity and signature;
- action and purpose;
- planned start/end;
- power;
- target SOC;
- max runtime;
- planned energy;
- price metadata;
- captured SOC;
- captured operating mode.

A deterministic SHA-256 fingerprint identifies the captured envelope.

Any post-capture change in slot, identity, signature, action, purpose, start/end, power, target SOC or runtime aborts the rehearsal fail-closed.

## Transaction rehearsal

The rehearsal exposes these non-physical intent phases:

PRECHECK
-> ZERO_POWER_INTENT
-> MODE_SWITCH_INTENT
-> WAIT_POST_MODE_INTENT
-> POST_MODE_REVALIDATION
-> DIRECTION_INTENT
-> POWER_INTENT
-> MONITOR_INTENT
-> SAFE_RETURN_INTENT
-> COMPLETE_DISARMED

No phase performs a Home Assistant service call.

Successful preparation ends at:
`prepared_disarmed`

An invalidated captured envelope ends at:
`aborted_disarmed`

A Step 5A gate that is not ready ends at:
`blocked_disarmed`

## External Anker EMS coexistence

The existing anker_ems integration remains the only physical battery controller.

DOEMS only observes battery state.

In self_consumption, Step 5B does not require post-mode direction or setpoint entities.

If the battery is externally placed in third_party_control, Step 5B requires the observed post-mode path to be ready and fails closed on conflicting direction or power setpoint.

## Hard physical boundary

Alpha7.24 keeps these invariants permanently false:
- automatic_execution_armed;
- step5b_authority_fence;
- step5b_service_calls_performed;
- service_calls_performed;
- physical_execution_authority.

There is:
- no arm switch;
- no execute action;
- no mode write;
- no direction write;
- no power write;
- no async_run_* or async_execute_* Step 5B method.

## Restart semantics

The Step 5B envelope is runtime-only and is not persisted.

After a Home Assistant restart or integration reload, Step 5B starts without a captured envelope and must pass the full Step 5A chain again before a new envelope can be prepared.

## Central validation sensor

sensor.doems_ems_shadow adds:
- step5b_status;
- step5b_envelope_ready;
- step5b_envelope_fingerprint;
- step5b_envelope;
- step5b_transaction_phase;
- step5b_transaction_ready;
- step5b_rehearsal_phases;
- step5b_blockers;
- step5b_warnings;
- step5b_abort_reason;
- step5b_authority_fence=false;
- step5b_service_calls_performed=false.

## Live validation target

A start-ready automatic planner action that reaches Step 5A ready_disarmed should reach Step 5B prepared_disarmed when no Step 5B blocker exists.

Physical execution must remain impossible.

Step 5C / any physical authority remains outside this release.
