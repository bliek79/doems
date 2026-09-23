# DOEMS 0.1.0-alpha.17 - Step 12.6 Restart / Recovery & Observability

## Scope
Step 12.6 makes the non-actuating Step 12.5 Execution Controller Shadow restart-safe and persistently auditable. It adds no physical battery authority.

## Added
- Component-owned Home Assistant Store for the execution-shadow lifecycle and audit state.
- Persistent bounded run history, last-run summary, counters and handled execution identities.
- Fail-safe detection of a shadow run that was active before integration reload or Home Assistant restart.
- Interrupted shadow runs are never resumed automatically; they are finalized as `restart_recovery`.
- Persisted handled identities prevent the same old execution identity from being restarted after recovery.
- Compact recovery observability on `sensor.doems_ems`: store status/error/last-save, recovery status/reason, interrupted-run flag, recovered identity and slot.
- Fixed recovery safe-return preview remains `0 W -> wait 1 s -> self_consumption`.

## Restart policy
- `DOEMS Automatic Execution` always starts OFF after setup/reload.
- No RestoreEntity path exists for the automatic arm.
- Persisted shadow data cannot create `execution_permitted` or physical authority.
- An active pre-restart shadow run becomes a fail-safe recovery record; it is not resumed.

## Safety boundary
Step 12.6 remains fully non-actuating:
- execution_controller_invoked=false
- mode_switch_performed=false
- direction_written=false
- power_setpoint_written=false
- safe_return_performed=false
- service_calls_performed=false
- physical_execution_authority=false
- no Home Assistant control service is called by the execution shadow

The existing `anker_ems` controller remains the physical battery authority.

## Validation target
After installation/reload, confirm:
1. automatic arm is OFF;
2. execution shadow is inactive unless a new explicitly armed-ready identity appears;
3. persisted run history/counters survive reload;
4. an interrupted synthetic/live shadow run reports restart recovery without physical writes;
5. Step 12.7 live shadow acceptance remains a separate next gate.
