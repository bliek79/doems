# DOEMS 0.1.0-alpha.8.1 - Manual Plan Lifecycle Fix

## Scope

Alpha8.1 is a focused live-validation fix on top of Alpha8.

It restores the missing manual plan lifecycle handoff that exists in the working `anker_ems` implementation, while keeping DOEMS standalone and non-actuating.

## Live issue found in Alpha8

A manually edited plan was stored correctly with:

- `origin=manual`;
- user-selected action, start time, power and target SOC;
- persistent Plan Store ownership.

However, the plan remained:

- `lifecycle_status=concept`;
- `lifecycle_reason=plan_changed`.

Because no DOEMS lifecycle service existed to promote the manual plan to `pending`, the Scheduler correctly ignored it.

## Copied working behavior

The existing working EMS uses an explicit plan lifecycle action:

`concept -> pending -> Scheduler`

Alpha8.1 copies that behavior into DOEMS itself.

No runtime dependency on `anker_ems` is introduced.

## Added

- `doems.schedule_plan`
  - validates plan slot;
  - requires an action;
  - requires a valid future start time;
  - forces `execution_mode=gepland`;
  - marks the plan `pending`;
  - sets `lifecycle_reason=scheduled_by_user`;
  - refreshes the DOEMS Scheduler.

- `doems.cancel_plan`
  - marks the selected plan `geannuleerd`;
  - sets `lifecycle_reason=manual_cancel`;
  - refreshes the DOEMS Scheduler.

## Deliberately not added

Alpha8.1 does not copy physical execution controls yet.

In particular:

- no `start_plan_now`;
- no battery mode write;
- no charge/discharge direction write;
- no power setpoint write;
- no controller or execution authority.

Those remain part of later roadmap steps.

## Safety boundary

Unchanged from Alpha8:

- `execution_mode=validation`;
- `automatic_execution_armed=false`;
- `service_calls_performed=false`;
- `physical_execution_authority=false`.

## Live validation after installation

1. Fill a manual plan slot.
2. Call `doems.schedule_plan` with that slot.
3. Confirm:
   - `origin=manual`;
   - `lifecycle_status=pending`;
   - `lifecycle_reason=scheduled_by_user`.
4. Confirm the Scheduler now sees the plan as future or start-ready.
5. Restart Home Assistant.
6. Confirm the manual plan remains persistent and is still owned by DOEMS.
