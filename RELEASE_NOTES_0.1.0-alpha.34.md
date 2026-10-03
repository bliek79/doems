# DOEMS 0.1.0-alpha.34 - Verified Physical Setpoint Handoff Adapter

## Classification

Alpha34 is a canonical DOEMS host/platform adapter and **not** a correction to the copied Anker EMS alpha76 logic.

The alpha33 live retest proved that the earlier Scheduler-selection loss was resolved. The manual scheduled 500 W charge then reached the physical handoff and was stopped by the unchanged Alpha76 monitor with `power_setpoint_changed`.

The official Anker control entity can return from Home Assistant `number.set_value` and then revert its control-state when the underlying write was not retained. Alpha34 verifies that host-level acceptance before allowing the normal Alpha76 runtime monitor to remain in control.

For every future "100% Anker alpha76 copy" audit, this adapter is canonical and must not be removed merely to make DOEMS architecturally identical to Anker. The definition remains 100% functional/behavioral Alpha76 parity with necessary DOEMS-native transport/host adapters.

## Fix

- Keeps `ems_execution.py` byte-identical to the verified Anker alpha76 source.
- Keeps the Alpha76 10 W `power_setpoint_changed` tolerance unchanged.
- Adds a DOEMS runtime wrapper for manual physical execution.
- After the frozen Alpha76 controller writes direction and power, the wrapper samples the Home Assistant power-setpoint control state three times after a short settle period.
- A confirmed setpoint continues under the normal Alpha76 monitor.
- An unconfirmed/reverted setpoint triggers the existing Alpha76 safe-stop and becomes retryable inside the already-valid manual start window.
- Manual scheduled execution remains independent of the Automatic Execution arm.
- Direct manual execution services use the same host-level verification.

## Frozen source behavior remains unchanged

Planner, Plan72, Planner Action Bridge semantics, Plan Store semantics, Scheduler, Prestart, Safety Guard, Action Controller, Execution Controller, physical test behavior, automatic arm semantics, safe return and the runtime monitor are not relaxed.

## Live validation

Alpha34 still requires the same 500 W manual scheduled Home Assistant live retest with Automatic Execution DISARMED before Step 4 can be marked green.
