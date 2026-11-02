# DOEMS 3.0 alpha.7.6 — Quarterly refresh and actionable safety hours

## Quarter-based recalculation

Normal SOC, forecast and price notifications are collected for the next native
quarter window. They no longer invalidate/restart a complete optimization on
every change. Source validity is still checked immediately. Manual/protected
plan constraints, safety/power configuration changes and SOC crossing below
reserve or hardware minimum remain immediate exceptions. Source recovery and
startup can recalculate immediately. An obsolete quarter result cannot publish.
New diagnostic attributes expose `calculation_count`, `deferred_refresh_count`
and `refresh_policy` alongside the existing generation and capture timestamps.

## Alpha84 actionable safety hours

Safety grid energy is aggregated per actual UTC source hour (distinct during
DST fallback). The 0.10 AC-kWh threshold is applied to the covered source hour,
including partial hours, rather than to each quarter. Safety commands are not
compacted across an hour boundary. Subthreshold commands are removed and the
same SOC model replays the remaining route. The same safety allocator searches
other feasible hours; protected/manual commands are retained. Diagnostics record
suppressed windows and their original source-hour energy.

The allocator now requires actual additional grid safety energy to cover the
stored-energy deficit when selecting power. Avoided household discharge during
a forced-charge command is no longer sufficient to justify a 100 W reserve-hold
pattern. This does not invent a physical battery hold mode or a second planner.

If suppression leaves a residual physical reserve shortfall without a feasible
alternative, the result is explicitly `limited` with the real shortfall. No
suppressed charge remains credited to SOC. Hardware minimum, energy conservation,
complete command phases, manual ownership and trading protections remain checked.
The Bridge additionally rejects a non-conforming source action as requiring
replanning, rather than allocating it while its source still credits that energy.

## Verification boundary

New scenarios cover real grid-energy purchase versus avoided household discharge,
source-hour threshold boundaries, replayed SOC after suppression, actionable
hours, batching SOC/source events until a quarter, immediate SOC safety crossings,
and the existing manual/stale-worker/source-loss/restart scenarios.
The existing reserve test distinguishes an honest subthreshold residual shortfall
from a fully reserve-satisfied route; it still enforces the hardware floor and
bounded shortfall. Energy and execution-authority protections are not removed.
The numerical replay budget and 7000-projection regression bound are retained.
Only reviewed corrected algorithm/source digests are updated.

Publication requires the full Python 3.12 and 3.13 suites and release validation
in GitHub Actions to pass. Entity IDs, unique IDs, existing release tags and
all dashboard visuals remain unchanged. No physical execution authority or
Home Assistant installation changes are introduced. Live chapter-7 test 2 and
the observed runtime frequency must still be checked after installation.
