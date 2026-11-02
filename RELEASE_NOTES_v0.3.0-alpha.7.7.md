# DOEMS 3.0 alpha.7.7 — Restore reserve after safety-hour suppression

Alpha.7.6 permanently excluded source hours after suppressing a sub-0.10 kWh
safety charge. The resulting replay could reveal a larger, actionable energy
need in that same hour, but the allocator could no longer use it. Live chapter-7
test 2 exposed the defect with 47% initial SOC and an avoidable future reserve
undershoot. The earlier `limited` outcome was not an acceptable repair.

## Fixed

- Reconsider previously suppressed hours when the actual replay reveals a
  real remaining battery need. A small deficit is not ignored just because
  the minimum actionable new command is larger than that deficit. Preserve price-first chronological
  candidate ordering and the same causal SOC simulator.
- A reopened hour must actually deliver at least 0.10 grid-safety AC-kWh. Enforce
  that constraint in the maximum-power feasibility check, integer power search
  and final candidate acceptance. Do not merely re-enable the old small command.
- Clear obsolete blocked-deadline decisions after a successful reopening so
  earlier reserve gaps are assessed again against the updated route.
- Reject mathematically impossible reopenings without expensive replays: even
  one continuous new command requires two minutes of preparation. In particular,
  a 100 W hardware limit cannot buy 0.10 kWh within one source hour.
- Expose `reopened_safety_hours` in the existing action-window search attributes,
  alongside suppressed windows, with the real new hourly energy.

Reserve recovery has priority over leaving a feasible residual gap. The minimum
actionable batch may exceed a small deficit, within existing capacity/power
bounds. A genuinely impossible 100 W source-hour case remains explicitly limited
and contains no fictional SOC credit.

## Regression evidence

A compact case derived from the reported SOC/configuration uses 47% initial SOC,
7.2 kWh capacity, 5% hardware minimum plus 5% reserve, 92% efficiencies and 3200 W
limits. Alpha.7.6 produces about 0.193 AC-kWh remaining need and 7.54% minimum SOC.
The regression test fails against the frozen previous source. The repaired
allocator reopens the required earlier hour with about 0.1018 kWh, keeps SOC above
10%, produces no reserve breaches or remaining need, and passes the actual Bridge.
This is a derived deterministic regression, not a claim to have replayed the
user's complete live forecast.

The original strict reserve assertions for the constant/variable/low-load
practical routes and the Alpha84 earlier-bridge-price scenario are reinstated.
They no longer accept a limited residual-shortfall result. The original replay
budget, numerical tolerances, 7000-projection bound and all other algorithm
source digests remain protected; only the corrected safety allocator and its
reviewed complete-file SHA are updated.

The full Python 3.12/3.13 suites and release validation must pass before publication.
Live chapter-7 test 2 remains open until the new live route is checked.
Quarter-based refresh, immediate manual/safety exceptions, price provenance,
slot ownership, entity/unique IDs, dashboards and existing release tags are
unchanged. No physical execution authority or Home Assistant installation
changes are introduced.
