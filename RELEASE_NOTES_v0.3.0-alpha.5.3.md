# DOEMS 3.0 Alpha 5.3 Plan72 practical action windows

Plan72 now calculates practical automatic charge/export windows and their exact
72-hour energy/SOC route together. The previous max-power sub-minute safety
segments could not be converted directly to useful automatic actions. Applying
the old DOEMS Bridge to their quarter totals changed the underlying route.

## Behavior

- Automatic windows start and end at exact UTC quarter boundaries, range from
  15 minutes to 12 hours and include one two-minute preparation phase.
- Preparation conservatively uses zero battery power: PV supplies the home,
  surplus exports and the remaining home deficit imports. No phantom battery
  charging or household battery discharge is credited during preparation.
- Charging uses a suitable setpoint in 10 W steps, at least 100 W and never
  above the configured direction limit. The available capacity bounds the
  full-window power; the planner does not intentionally solve each deficit
  with a short max-power pulse.
- Safety scheduling tries existing window capacity, checked extensions and
  price-ranked earlier quarters. Feasible adjacent windows merge only after
  full-route verification. Candidate coverage also includes recent deadline
  quarters so unusable cheap windows cannot starve recovery.
- Optional trading is checked against the fixed pre-trade route, actual route
  costs and the existing margin. Reserve, household coverage, manual constraints
  and PV-storage opportunities remain protected. Optional trades may not create
  an early-stop pulse in another planned window.
- A real shortage or exhausted search budget remains visible as limited.
  Raw deficits and the Alpha5.2 numerical tolerance accounting remain intact.

## Entities and contract

No new public entities. The existing 35 Plan72 and 11 Energy Need identities are
preserved. The existing Plan72 Timeline attributes add `action_windows`,
`action_window_count`, `action_window_contract`, `action_window_search` and the
frozen `battery_parameters`. Window lists are excluded from recorder history.
Each window retains actual flows, projected SOC, limits, preparation/power/end
times, a stable identity and a full-content signature. Parent plan generation
and input fingerprint identify the one published calculation.

The HA runtime always selects the practical-window contract. The pure evaluator
retains its default Alpha5.2 calculation path solely for backward-compatible
callers and regression comparisons. It is not a second running HA planner.

## Boundaries

This is Chapter 5 only. No Action Bridge entities, Plan Store, slots, Scheduler,
execution permission or physical battery commands are included. Chapter 6 stays
on its separate unfinished development branch. Main and existing tags/releases
are not replaced.

The search remains a bounded deterministic heuristic, not a claim of globally
optimal trading or the fewest possible daily actions. A window is a maximum
runtime: actual safety limits/target attainment may still stop a battery early.
100 W and the two-minute allowance are planning assumptions inherited from the
reference route, not a live validation of every Anker control limit or handoff.

## Installation and validation

After publication select v0.3.0-alpha.5.3 in HACS and restart Home Assistant.
Confirm the 35 Plan72 entities still exist and the Timeline reports
`action_window_contract: quarter_windows_v1`. Inspect window count, durations,
power, preparation, reserve breaches and shortage. Observe a natural SOC update.
This release does not rename/delete local entity registrations automatically.

Code tests, CI and package provenance are checked before publication. Actual
Home Assistant installation, window behavior on live forecasts, natural SOC
refresh and preparation/physical behavior remain live validation work; they
are not claimed as completed by a successful CI run.
