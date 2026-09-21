# DOEMS 0.1.0-alpha.7.23 - G6 Step 5A Quarter-roll Planner Identity Continuity Fix

## Scope

Alpha7.23 fixes the live Step 5A blocker `planner_identity_missing` discovered after Alpha7.22.

The fix is deliberately narrow:
- preserve the existing planner identity only for the same planner-owned pending action across one native 15-minute rolling shift;
- keep the planner signature revision-sensitive;
- leave Prestart, Safety, Execution Handoff, Final Revalidation and Mode-switch Preview unchanged;
- leave all physical execution authority disabled in DOEMS.

## Root cause

The frozen Alpha76 planner identity includes:
- action;
- purpose;
- source-hour anchors;
- planned end time.

That is stable for fixed hourly anchors. DOEMS, however, keeps a native rolling quarter start. A stored pending action such as 11:00-12:00 can therefore reappear in the current bridge preview as 11:15-12:15. Without continuity handling, the current preview receives a different identity and Prestart correctly fails closed with `planner_identity_missing`.

## Quarter-roll continuity contract

A current candidate may inherit the stored pending planner identity only when all of the following are true:
- the stored slot origin is `automatic_72h_planner`;
- lifecycle is `pending`;
- a stored planner identity exists;
- action is unchanged;
- purpose is unchanged;
- the current candidate itself is valid;
- the new start moved forward by more than 0 and no more than exactly 15 minutes;
- the old and new execution windows overlap;
- the original Scheduler start window has not expired.

If any condition fails, the current candidate keeps its newly calculated identity and the existing fail-closed behaviour remains.

## Revision signature

The inherited identity does not freeze the plan revision. `planner_signature` remains recalculated from the current candidate, so SOC, target, energy or power revisions remain observable and Prestart can still report a revision change.

## Physical boundary

Alpha7.23 changes no physical control path.

Hard invariants remain:
- `automatic_execution_armed=false`;
- `service_calls_performed=false`;
- `physical_execution_authority=false`;
- no Anker mode, direction or power service call is added;
- the existing `anker_ems` integration remains the physical battery controller.

## Validation

Regression coverage includes:
- 11:00 -> 11:15 preserves identity;
- the signature remains revision-sensitive;
- >15 minute shifts do not inherit identity;
- different action does not inherit identity;
- different purpose does not inherit identity;
- non-overlapping windows do not inherit identity;
- an expired original start window does not inherit identity;
- the DOEMS physical boundary remains closed.

## Live validation target

After installation, validate through `sensor.doems_ems_shadow`.

For a start-ready automatic action, the expected result is:
- `planner_identity_missing` is absent;
- Prestart can progress based on its remaining live checks;
- downstream gates may progress to at most `ready_disarmed`;
- all DOEMS physical execution flags remain false.

Step 5B remains blocked.
