# DOEMS 3.0 Alpha 8.3 — Continuous safety charging near full SOC

Fixes a remaining compaction failure reported after Alpha 8.2: three adjacent
safety-charge windows at 3,200 / 270 / 3,060 W remained separate because rounding
the merged power upward added energy that could not fit below full SOC.

The Alpha84 upward rounding remains the first choice. For safety charging only,
Plan72 can also try the immediately lower 10 W step when the first candidate
fails its route checks. This is a bounded repair to DOEMS's quarter-window
compaction, not a claim that Alpha84 contains the same fallback. Both candidates
use the same full 72-hour replay and unchanged checks for reserve, household
shortfall, manual plans, solar charging and downstream capacity. If neither
candidate is feasible, the original windows remain. Trading is unchanged.

The isolated reproduction uses the reported powers and SOC changes, with no
home/PV flows during the reproduction. It now produces one 45-minute window,
one two-minute preparation and 1,970 W for 43 minutes (1.411833 kWh). The smaller
rounded energy is reflected in the projected end SOC; command_target_soc remains
100%. This is not a replay of the user's complete live forecast.

Regression tests cover the reported sequence, rejection when a lower power
would create a later household shortfall, and one eligible action through the
real Action Bridge. Live acceptance remains outstanding.

No entity IDs, unique IDs or dashboard changes. Scheduler cadence and persisted
slot protection are unchanged. Physical execution authority and execution
remain false. Existing releases and main are unchanged.
