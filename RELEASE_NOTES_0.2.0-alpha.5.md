# DOEMS 0.2.0-alpha.5 - Manual Lifecycle Expiry

## Purpose

This release implements R4 of the reset route: manual pending plans may no longer keep one of the three active Plan Store slots occupied after their complete start window has passed.

R0 Forecast Reset Baseline, R1 Battery Input Contract, R2 Manual Plan Store and the R3 manual charge/cancel/SOC/dashboard chain were proven live before this build. The separate manual-discharge retest remains explicitly parked and is not claimed green by this release.

## Functional contract

Only a manual-origin plan with lifecycle `pending` and execution mode `gepland` is an expiry candidate.

The complete start window is:

`[start_time, start_time + max_start_delay_min]`

The exact window end remains valid. Expiry occurs only when current time is strictly later than the window end and the plan has not moved to an active/running lifecycle.

When such a plan expires:

- a compact terminal audit event is persisted with status `verlopen`;
- reason is `manual_start_window_expired`;
- the active planslot is atomically reset to its normal empty/editable defaults;
- lifecycle reason on the released slot becomes `manual_expired_released`;
- Plan Store listeners are notified immediately;
- R3 SOC projection therefore removes the expired manual commitment immediately;
- the same planslot is directly reusable without a manual `doems.clear_plan`.

## Added

- `manual_plan_lifecycle_model.py`
  - pure, deterministic expiry evaluation;
  - exact-boundary semantics;
  - fail-closed blockers for malformed pending plans;
  - earliest-expiry deadline selection.
- `manual_plan_lifecycle.py`
  - lightweight point-in-time timer;
  - evaluation at integration startup/reload;
  - reevaluation after Plan Store changes;
  - no forecast recomputation.
- `sensor.doems_manual_plan_lifecycle`
  - lifecycle status;
  - blockers;
  - next expiry timestamp/slot;
  - last released slots;
  - compact persisted terminal audit events.
- Plan status sensors expose their most recent `last_terminal_event`.

## Persistence

Terminal expiry evidence is stored alongside the existing manual Plan Store under a bounded `terminal_events` collection. It is deliberately kept outside the three active slots, so audit evidence remains available without consuming planning capacity.

A Home Assistant restart after cleanup therefore reloads the released slot as empty rather than reviving the stale pending plan.

## Fail-closed behavior

A manual pending slot is not automatically cleared when any required expiry input is malformed. Invalid/naive start time, invalid start delay, invalid action or invalid execution mode yields explicit lifecycle blockers and leaves the active slot untouched.

## Safety boundary

R4 remains a Plan Store/lifecycle layer only.

- no automatic planner;
- no Scheduler selection;
- no Safety or Prestart;
- no operating-mode switch;
- no battery direction or setpoint writes;
- no Home Assistant battery service calls;
- `physical_execution_authority=false`.

The timer only evaluates time/lifecycle state and releases a valid stale manual pending slot.

## Validation

Required automated validation includes:

- before window end: no expiry;
- exact window end: no expiry;
- one second after window end: expiry;
- only manual + pending + scheduled is eligible;
- malformed pending plan blocks fail-closed;
- earliest of three pending deadlines is selected deterministically;
- released slot is reset with `new_manual_plan()`;
- compact expiry audit evidence is retained;
- R3 only treats `pending` and `actief` as manual SOC commitments;
- lifecycle runtime contains no execution/automatic-planner authority;
- full existing repository test suite remains green.

## Live exit gate

R4 is only LIVE GREEN after Home Assistant proves:

1. create a future manual plan with a short start margin;
2. leave it intentionally unexecuted;
3. before the full start window ends, the plan remains pending;
4. after the window ends, the active slot automatically becomes empty/reusable;
5. `sensor.doems_manual_plan_lifecycle` records the terminal expiry event;
6. `sensor.doems_manual_soc_projection` removes that slot from `manual_commitment_slots`;
7. the Plan72 SOC effect and dashboard next-action indication disappear;
8. the same slot can immediately be edited and scheduled again without `doems.clear_plan`;
9. after a Home Assistant restart, the stale expired plan does not return;
10. Scheduler, automatic planning and physical execution remain absent.
