# DOEMS 0.1.0-alpha.40 - Manual Plan Replay Fix

Alpha40 fixes a live-validation defect found immediately after Alpha39: a handmatige Plan Store action could keep stale derived metadata after the user changed its start time or other control values. That could make a valid pending action for today invisible to Plan72 commitment replay.

## Fix
- Explicit user edits now clear stale `planned_energy_kwh` and `planned_end_time` metadata.
- Plan72 commitment extraction repairs a missing or invalid end time from `start_time + max_runtime_h` instead of silently dropping the commitment.
- Manual pending/active actions inside the 72-hour horizon remain hard commitments and affect projected SOC and later safety/trade decisions.

## Preserved contracts
- Native DOEMS transport remains 15 minutes / 72 hours / 288 slots.
- Alpha39 Plan Store commitment replay remains intact.
- Design C reserve semantics remain fixed at 12% operational/execution reserve.
- Physical execution authority remains disabled during shadow validation.
- Frozen Alpha76 parity and Alpha33/34/35 regression contracts remain protected.

## Validation
Alpha40 adds a regression guard for stale manual-plan derived metadata and runs the complete DOEMS CI, planner/scheduler/safety, prices/forecast, JSON and full pytest suites before publishing.
