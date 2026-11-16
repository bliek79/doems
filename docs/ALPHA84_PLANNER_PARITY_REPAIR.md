# Alpha84 planner parity — repair in progress

Date: 2026-11-15. Base: DOEMS `95cc001d99b5951a02ca199dcbc34f13a7ff17d2`
(Alpha 8.4). Reference: Alpha84 `6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d`.

## Status

**Not repaired. Not approved for publication.** The full planning-chain
comparison fails. Existing green unit tests and the earlier grouping oracle
do not prove equivalence to Alpha84. No integration/runtime changes are made
by this investigation checkpoint.

## Source-port implementation checkpoint

`custom_components/doems/alpha84_planning.py` now contains the original Energy
Need, Preview and Plan72 functions. The decision bodies are preserved; HA time
utilities are replaced with pure datetime helpers and the original capacity
and technical-minimum constants become per-call parameters. The upstream
license is included. No shared battery configuration is mutated.

Eleven tests compare complete dictionaries (not selected totals) against the
unchanged frozen source. They cover the three differential scenarios at 7.2
and 7.1 kWh, different technical floors, concurrent independent calculations,
solar and negative prices at four starting SOCs. All pass without relaxing
expected results or tolerances.

**This port is not connected to the active runtime.** The existing runtime
parity gate remains failing and publication remains blocked.

## Confirmed requirement and quarter adaptation

User decision, 2026-11-15: “dezelfde strategie en verantwoordelijkheden als
Anker EMS, met behoud van kwartierprijzen en aaneengesloten laadvensters”.
There is no remaining request for a choice between hourly prices and quarter
prices. Do not average away quarter prices.

The port now accepts `interval_minutes=15` (288 rows over 72 hours). The default
60-minute mode remains exactly equal to the frozen source. Adaptations are
explicit: slot boundaries, fractional elapsed interval, duration-based power
limits, horizon length and the original TWO-HOUR usable-solar condition (eight
consecutive quarters, not two). Economic best-pair ordering is retained.

`alpha84_action_bridge.py` ports the original full-chain grouping. Its explicit
interval changes adjacency and interval end only. It groups all consecutive
eligible allocations before selecting the three-slot preview, and subtracts
one handoff allowance per group. Source thresholds and ownership logic are
retained; they still require verification against real quarter allocations
during integration, not an assumption that grouping alone proves parity.

Eighteen focused tests pass: full-dictionary hourly source equivalence, battery
configuration isolation, native quarter-price selection and energy bounds,
partial quarters, two-hour solar recognition and grouping of five complete
windows before three-slot selection. Native-quarter power-bound tests do not
claim hourly energy-volume equivalence: the deliberately unique best quarter
in that case has only .8 kWh capacity at 3200 W. Flat-price-hour trading volume
and the complete manual-constraint route still need integration verification.

Remaining work: integrate this strategy into the single active Plan72 route,
preserve manual/due/active constraints and the existing entity/provenance
contracts, migrate Bridge validation to the restored responsibility split,
and run the full runtime differential and lifecycle suites. No release yet.

## Reproducible evidence

`scripts/compare_alpha84_planners.py` runs the unchanged reference Energy Need,
Planner Preview, Plan72 and Action Bridge, followed by current DOEMS Plan72 and
Action Bridge. It does not load HA, Store writers or execution controllers.
The full input, both results, all candidates and every hourly difference are
retained in its JSON output; no three-slot truncation is used for comparison.

Both sides use 7.2 kWh, SOC as specified per scenario, 5% technical minimum,
5% software reserve, 92% efficiencies and 3200 W charge/discharge limits.
The additional reference execution buffer is explicitly set to zero on both
sides to isolate strategy from configuration. Forecast prices are constant
within each hour; home and solar energy are divided equally into four quarters.
Reference source precision, not observed discrepancies, defines comparison
tolerances (.0005 kWh per hourly flow and .05 SOC percentage point).

| Scenario | Alpha84 | DOEMS Alpha 8.4 |
| --- | --- | --- |
| Passive control, 80% SOC | No candidates | Identical hourly flows/SOC; no candidates |
| Safety valley, 60% SOC | 2 candidates; 8.847 kWh safety charge | 17 candidates; 7.719833 kWh safety charge |
| Repeated trading opportunities, 50% SOC | Buy 3.2 kWh; sell 3.2 kWh; 2 candidates | Buy 0 kWh; sell 2.647667 kWh; 1 candidate |

These are deterministic constructed scenarios, **not the user's live forecast**.
They prove non-equivalence but do not establish why a particular live slot was
empty. Three slots are capacity, not a requirement to invent three actions.

## First structural divergences

1. Alpha84 Preview allocates stored energy before execution-window construction.
   Its Plan72 projects hourly solar, safety charge, home discharge and the chosen
   trade. DOEMS `_safety_windows` instead searches 10 W physical quarter
   commands, repeatedly subtracting preparation during the allocation itself.
   In the safety scenario the first hourly difference is at hour 18: Alpha84
   allocates 3.2 kWh grid charge; DOEMS delivers 1.213333 kWh.
2. Alpha84 Preview chooses one chronological buy/sell pair by greatest net
   margin and retains the first pair on a tie. Profitability also depends on
   the original safety-charge-needed condition. DOEMS `_trade_windows` instead
   considers direct sales and multiple pairs, bounds its search, and applies
   incremental route-cost and extra household/solar constraints. In the trade
   scenario it skips the reference purchase at hour zero.
3. DOEMS subsequently groups and replays command windows, which can change
   energy/SOC already used during allocation. Grouping tests alone cannot
   validate this preceding decision process.

## Repair acceptance

- Restore reference allocation and trade selection before command construction;
  do not mask differences by filling slots or loosening expected values.
- Reconcile the existing quarter-data contract and manual/active plan overlays
  explicitly. The reference hourly arithmetic and DOEMS physical command
  simulation differ: a silent substitution would break existing contracts.
- Compare the full 72-hour energy/SOC route and all candidates, including
  withheld candidates, then test persistent slot assignment separately.
- Include variable/negative prices, solar, safety plus trade, manual priority,
  active ownership, target arrival, capacity limits and partial starting hours.
- Keep source generation/fingerprint/identity/revision checks, quarter refresh
  policy and execution authority disabled. No HA/dashboard changes.
- Publish only after the differential checks pass or each remaining difference
  has an explicit accepted requirement. Do not accept `limited` merely because
  it makes a DOEMS-only test pass.

## Reproduction

```sh
.venv/bin/python scripts/compare_alpha84_planners.py --output build/alpha84-planner-parity.json
.venv/bin/python -m pytest tests/test_alpha84_planning_oracle.py -q
```

The first command currently exits 1 (equivalence failed). The second checks
the oracle harness itself and passes three tests; it does not certify repair.

## Runtime connection checkpoint

The worker now passes `compute_strategy_bundle` into `calculate_plan72`.
The reference's valid candidate prefix is projected through the existing causal
Plan72 simulator, preserving explicit manual/due/active constraints and source
window serialization. Overlapping automatic windows are suppressed. Mixed
safety/trade purposes currently fail closed pending contract migration; this is
an unresolved compatibility issue, not an accepted final behavior.

Validation: 22 runtime tests and two new strategy-to-Bridge/manual integration
tests pass. Full suite: 897 passed, three failed in 133.32 seconds. The failures
are existing frozen-source/release-contract checks for the changed calculator
and worker. Their hashes have deliberately NOT been updated to imply completed
review. The differential gate still needs to exercise the active factory path
and account explicitly for the approved quarter-resolution adaptation.

**Not release-ready.** Manual-aware automatic allocation, mixed-purpose handoff,
and full-chain equivalence remain unverified. Runtime connection alone does not
prove that the original functional request has been completed.

## 2026-11-16 - da07656 recovered and H8 repair resumed (NOT RELEASED)

This section supersedes the **checkpoint-only** state descriptions above; the
historical observations remain intact. The user supplied
`DOEMS_reparatie_da07656_overdracht(1).zip`. All five original unpushed commits
were recovered from the included Git bundle; `git bundle verify`, `git fsck`,
SHA256 manifest verification, and the HEAD `da07656d06cc2417e6d17d550633d10beb18a3ac`
were confirmed. Work continues on a *local independent development branch*,
`doems3-ch8-parity-repair-after-da07656`, descended from this exact checkpoint.
This branch is NOT on GitHub and is not published.

### Implemented and locally regression-tested

- The native Plan72 baseline first projects **all manual/due/active protected
  commitments**, including their SOC-energy changes and occupied quarters. The
  resulting time/energy commitments are supplied as explicit inputs to Alpha84
  Preview and Plan72 **before automatic allocation and best-pair selection**.
  This avoids post-hoc suppression as the only manual protection mechanism.
- A charge window containing both safety and trade charge is projected as one
  physical action and retains its separate flow attribution. Plan Store mapping
  and persistence preserve the safety/trade split, including after restoration;
  no new entity IDs or Store slots were created.
- The frozen Alpha84 60-minute source port remains exact in its comparison
  tests. The native 15-minute implementation retains distinct quarterly
  prices, adapts 0.01-kWh *numerical* epsilon by interval duration, and
  evaluates the original 0.10-kWh **actionable safety** threshold across the
  corresponding source hour. Four adjacent equal-priced quarters represent
  one 3.2-kWh original buy/sell pair rather than a lone 0.8-kWh quarter.
- Native physical command handoff (two minutes) can reduce a 3.2-kWh source
  buy/sell pair to **3.093 kWh in each direction**. The physical buy and sell
  are constrained symmetrically, and Plan72 recomputes command SOC targets from
  the actually accepted earlier windows. `command_target_soc` remains distinct
  from `projected_end_soc`. A separate manual target limitation no longer
  invalidates otherwise safe preceding automatic trades, but reserve/battery
  physical breaches still block unsafe readiness.
- The source Alpha84 default execution buffer **2%** remains the normal
  strategy default; the differential fixture's explicitly configured **0%**
  buffer does not change that live configuration. The Bridge remains
  observational. `physical_execution_authority=false`, `execution_enabled=false`.
- `scripts/verify_alpha84_repaired_chain.py` now stores all 72 hours / 288
  quarters, original Alpha84 results, source-quarter results, native Plan72
  results, every original/source/native/Bridge candidate, rejection reasons,
  flow balances, and SOC/hourly differences. It exercises the actual native
  `calculate_plan72(..., strategy_factory=...)` factory route; independent
  worker regression tests exercise runtime `_evaluate` with real `Plan72Inputs`.

### Measured full-horizon comparison, *constructed* fixtures only

All three cases use the same synthetic original 72-hour forecast, quarter
energy distributed consistently without tariff averaging, 7.2-kWh fixture
capacity, SOC scenarios, 3.2-kW power, 92% efficiencies, 5% technical minimum,
5% reserve, and explicitly configured 0% comparison buffer. They are **not**
measurements of the installed battery or user-specific live forecasting.

| Scenario | Original candidates | Quarter source / native / Bridge candidates | Original/source/native 72h flow evidence | Full parity gate |
|---|---:|---|---|---|
| Passive control | 0 | 0 / 0 / 0 | Source, Alpha84 and native hourly energy/SOC identical | Pass for this fixture only |
| Safety valley | 2 | 2 / 2 / 2 | Safety grid AC: 8.845 / 8.879 / 8.433332 kWh; native Plan72 **limited**, remaining charge requirement 0.066888 kWh; native house import 1.887444 kWh | **FAIL / OPEN** |
| Repeated trading | 2 | 2 / 2 / 2 | Source and Alpha84 both buy/sell 3.2 kWh; native physical buys/sells 3.093 kWh after one preparation window each; native Plan72 ready | Numeric physical delta documented; not accepted as whole-route parity |

The full diagnostic stores **137** hourly source-vs-Alpha84 differences
in safety valley (and **155** source-vs-native differences), and **74**
source-vs-native differences in the repeated-trade case. Equal candidate
counts alone do **not** make these differences acceptable. In particular,
`remaining_physical_shortfall` in the safety case is still an **open failure**, not
an opportunity to relax tolerances or silently declare limited acceptable.

Reproduce full diagnostic:

```bash
python scripts/verify_alpha84_repaired_chain.py --output build/alpha84-repaired-fullchain.json
python -m pytest -q tests/test_alpha84_mixed_purpose_contract.py tests/test_alpha84_worker_entrypoint_parity.py
```

### Verified tests and intentionally closed publication gate

Python 3.13 functional regression suite **899 passed, 3 deselected**. The
three deselected *frozen protection/release tests* (`test_calculators_and_runtimes_are_frozen_reviewed_ch7_blobs`,
`test_ch7_preserves_reviewed_strategy_algorithms`,
`test_approved_release_contract_and_register_are_exact`) remain **RED**, not
rebaselined to accept ongoing differences. `tests/test_plan72_config.py` is
excluded locally because the `voluptuous` dependency is absent from this
isolated environment. The Python 3.12 runner is also unavailable locally.
Thus **the required full Python 3.12/3.13 CI/release gate has NOT passed**.
No claim is made about a new CI package, checksum, provenance or GitHub tag.

Remaining acceptance scope **H8-01 to H8-19 stays OPEN** pending full
criterion-specific evidence. In particular: resolve the observed safety-valley
physical shortfall without changing Alpha84 strategy or hiding differences;
finish all possible physical/strategy temporal parity cases and the complete
worker/Store/Scheduler lifecycle; verify frozen files and update reviewed
source hashes only *after* justified code review; execute full 3.12/3.13
GitHub CI; verify package, hash, provenance and pre-release; provide exact
install version and complete user live checks. Gas EnergyZero errors,
`unknown` trade fields, Anker battery-capacity `state_class` and B.R.I.C.K.
causation remain separate, unresolved issues.

**No tag, no new release, no merge to main, no Home Assistant change,
no physical execution.** This is a development checkpoint, not an
installable release, and Chapter 8 is **not** signed off.

## 2026-11-16 — recovered checkpoint follow-up: full-chain actionable safety (NOT RELEASED)

This supersedes only the earlier safety-valley *physical deficit* observation;
the earlier numerical results remain part of the historical evidence. The
original five recovered commits and the 919c98b integration checkpoint remain
part of the development history.

**Fault isolated:** the native 15-minute Alpha84 Bridge evaluated its 0.10-kWh
physical safety threshold inside each clock-hour bucket. A continuous safety
allocation beginning at 12:30 UTC contained 0.046 + 0.045 kWh before 13:00,
then further safety quarters. The isolated 0.091 kWh prefix failed the
hour-bucket test, so physical execution incorrectly began at 13:00 UTC.

**Fix:** for native 15-minute rows only, identify each complete contiguous
same-purpose safety allocation before assigning physical eligibility. Apply
the original 0.10-kWh *actionable window* minimum once to the combined
allocation; maintain separate safety/trade-purpose and discontinuity
boundaries. Keep 60-minute behavior exactly unchanged. This does **not**
average 15-minute prices, create artificial actions or reorder the Alpha84
trade decision. A disconnected collection of small allocations cannot pass
that same threshold merely because its combined sum exceeds 0.10 kWh.

The constructed same-input safety-valley now has **two** source, native and
Bridge candidates, with the second physical window **12:30–00:00 UTC**;
no reserve breach and `remaining_charge_need_kwh=0`. The earlier physical
0.066888-kWh deficiency has been eliminated. The first physical charge remains
honestly `limited` (`target_or_capacity_limited`): requested 6.808 kWh versus
6.453332 kWh delivered before reaching capacity/target. The second valid
window is still handed downstream. No artificial tolerance increase or
`limited -> ready` status substitution has been made.

A new explicit end-to-end regression tests the real `calculate_plan72` factory
route in that safety valley, in addition to quarter boundary/discontinuity
unit regressions. Original source-hourly candidate/energy differences from
native 15-minute execution, precision and the two-minute handoff are still
**not accepted as full strategy equivalence**. The complete review, 3.12/3.13
matrix and protected-source/release checks still block publication. No main
merge, version/tag/release, Home Assistant change or physical execution.

## 2026-11-16 — Acceptance clarification: different forecasts are expected (user-confirmed)

**Leading project constraint:** the original Anker EMS and DOEMS use different
forecast sources. Consequently, their live forecast values, predicted
consumption/solar yield, SOC trajectories, charge quantities and chosen
real-world start times **will normally differ**. Their absolute live
outputs **must never be a cross-project equality/release gate**. Prior
wording suggesting otherwise is superseded by this decision.

**What must match:** planning **strategy and responsibilities**, not
prediction outputs: safety first and before action creation; original
best chronological buy/sell pair, applicable tie-breaks and trade
conditions; manual / due / active protection during allocation;
connected eligible quarters grouped **before** three-slot selection;
original Scheduler and Plan Store responsibilities; execution buffer,
SOC safety, identities and deadlines. Retain DOEMS's own forecast input
and distinct 15-minute prices. Do not average tariffs into hourly prices.

**How to verify:** use constructed *equal-input* fixtures for
algorithmic comparisons where time resolution and constraints are
controlled. Verify decision rules, reasons for acceptance/rejection,
energy preservation and source-to-native mapping, rather than demanding
bitwise identical SOC or hourly flow totals between an hourly oracle
and 15-minute physical commands. Explain deviations attributable to
time granularity, the unchanged execution-preparation buffer, or
bounded physical delivery; treat genuinely unexplained decisions under
equivalent normalized input as defects. Compare each product's
**forecast-dependent live output against its own source data**, not
against the other product's live forecast.

**Release gate correction:** differences caused solely by *different
live forecasts* or demonstrably different 60-minute/15-minute physical
resolution are **NOT** reasons to withhold release. This does **not**
waive actual same-input strategy bugs, unfinished functional criteria
or the three separately failing reviewed-source/release-contract tests.
The independent GitHub matrix at run `43914837429` passed 917 functional
tests on Python 3.12 and 3.13; the three protected checks failed because
approved hashes/contracts still reflect older source. Review and
rebaseline those only against the intended, justified code changes,
with no test-expectation laundering. No merge/release/live validation
is claimed by this clarification.
