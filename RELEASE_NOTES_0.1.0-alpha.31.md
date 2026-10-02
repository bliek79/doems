# DOEMS 0.1.0-alpha.31 - Exact Anker Alpha61/76 Planner Parity

## Scope
Alpha31 removes the production planner-policy divergence and makes the proven Anker EMS Alpha61/Alpha76 planner core the direct DOEMS production decision source.

## Exact source baseline
The following planner files are copied from tag `0.0.1-alpha.76` of `bliek79/dummy-os-anker-ems`. These files are unchanged between the proven Alpha61 and Alpha76 references:
- `energy_need.py`
- `planner_preview.py`
- `planner_72h.py`

DOEMS retains only the transport adapter required to feed its native 15-minute / 72-hour / 288-slot forecast contract into the proven 72-hour Anker decision core.

## Restored production behavior
- Solar first.
- Safety charging remains first priority.
- Profitable trade remains available in Plan72 when safety charging also exists.
- Existing Solar Charge Delay behavior is preserved.
- Existing trade-reservation behavior is preserved.
- Existing dynamic reserve and 2 percentage-point execution buffer behavior is preserved.
- Existing charge/discharge efficiency and minimum trade margin behavior is preserved.
- No new planner blocker or policy rule is added.

## Production path
`ems_multirate.py` now calls the exact Alpha76 adapter directly. The later DOEMS `ems_policy_alpha20.py` policy is no longer in the production planner path.

## Unchanged
- DOEMS native 15-minute / 72-hour / 288-slot input architecture.
- Plan Store / Scheduler structure.
- Manual priority.
- Automatic execution arm and physical safe-return path.
- Existing DOEMS control-path safety gates.

## Version
`0.1.0-alpha.31`
