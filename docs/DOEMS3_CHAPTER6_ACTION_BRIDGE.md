# Chapter 6 Automatic Action Bridge development draft

Status: implementation and diagnostic regressions only. NOT approved for release.
Base: v0.3.0-alpha.5.2, af6a893fe2b85003d030525e9f60ee031fa800ce.
The original energy_need.py, energy_need_runtime.py and planner_72h.py remain
unchanged. planner_72h_runtime.py adds only frozen battery-parameter metadata.

The draft registers three sensors (Action Bridge Status, Action Candidates,
Action Slot Preview) and one binary sensor (Action Bridge Valid). They are
created when Plan72 is enabled. They are observer-only. No slots, storage,
scheduler handoff, automatic arm or physical services are added.

## Contract

Inputs are one complete native 288-quarter Plan72 runtime snapshot, exact
segments, generation, input fingerprint, calculated timestamp and the battery
parameters used for that same calculation. Explicit safety_charge, trade_charge
and trade_discharge are selected. Manual and passive segments are excluded.
Only exactly contiguous segments of the same purpose, power and target merge.

Outputs retain source segment references, total battery AC energy separately
from grid/PV/home contributions, SOC, power, energy, hard end, runtime,
identity, full-content revision signature and source-generation provenance.
The preview is the first three eligible candidates assuming free capacity; it
is not actual slot assignment. Identity uses purpose, quarter anchors and
nominal start. Generation is provenance rather than a revision of action
parameters. A changed set of quarter anchors creates a new identity.

Alpha84 chronology is reproduced: capped feasible charge retains its shortfall
and does not hold successors. A truly invalid candidate holds its entire tail;
an earlier valid prefix remains available. Limited Plan72 routes allow safety
recovery candidates while holding trading candidates.

## Blocking integration finding

The approved initial proposal combined exact Plan72 segment windows with the
old Alpha84 two-minute handoff subtraction. The real Alpha5.2 engine produces
short safety-charge segments followed by passive self-consumption inside the
same quarter. In the synthetic real-engine regression, the first safety segment
is 54.842145 seconds long and requests approximately 0.048748573 kWh. Subtracting
two minutes leaves no usable window and correctly blocks the chronological
chain. This is NOT evidence of a defect in the validated Plan72 calculation.

In addition, exact discharge segments already use the configured maximum
battery output. Subtracting handoff time makes their assigned energy infeasible.
The draft exposes these candidates as invalid, preserving the source route.
No power increase, passive-gap merge, window extension or alternative SOC route
has been introduced to hide this conflict.

A design decision is required before release: determine how the preparation
budget relates to the exact source action windows and the later execution
preparation state machine. Moving it before an action is not automatically
route-neutral: confirmed zero power can interrupt the preceding passive route.
Dropping the allowance or using whole-quarter envelopes must not be done silently.

The draft is deliberately not a releasable Chapter 6 implementation. The
reserved v0.3.0-alpha.6.1 has not been published. Home Assistant is unchanged.

## Verification

Tests cover real Plan72 translation and the blocking short-segment case,
Alpha84 third-candidate recovery, invalid-prefix behavior, mixed PV/grid energy,
home-plus-export battery output, exact timestamps and DST, stale plans,
identity/signature behavior, recovery routes, observer-only runtime invalidation,
entity subscriptions and unload. Frozen calculator blob tests protect chapters
4 and 5. Existing version assertions follow the draft manifest version; their
functional assertions remain intact.

Live installation and validation, release packaging, release checksums and the
C.6 work-document record remain pending. No release workflow is enabled here.

## Read-only old-window comparison

The user requested comparison with the original DOEMS route before deciding on
minimum duration or a new preparation contract. `scripts/analyze_action_windows.py`
provides a reproducible synthetic comparison with old main commit
`d0c3a133dadcb94136e0641f25644780bd395ad6` (old DOEMS alpha.9.11).
It uses the unchanged Plan72 `_Model.simulate` kernel for fixed-command replay.
The optimizer is not rerun to conceal new shortfalls. Exact segment replay is
first checked against the original route (SOC difference below 0.000001 point).

The old adapter groups adjacent explicit quarters of the same action/purpose,
sums their grid energy, computes average power (10 W steps, minimum 100 W), and
allows a maximum 12-hour window. The two-minute subtraction applies only to pure
safety charging. It does not bridge empty quarters or impose a minimum physical
charging duration. Its 11 existing bridge/Alpha83-84 contract tests passed in a
separate read-only export of that commit.

Synthetic results, not live measurements:
- Constant home demand without PV: 193 explicit source segments form three
  quarter windows. The old Bridge rejects the first as longer than 12 hours;
  no proposals are emitted. No full-horizon comparison of an empty prefix is
  interpreted as a valid alternative route.
- Variable demand with PV: 55 source segments form three windows. The first
  proposal passes, but the second fails the old target-SOC range check. The
  resulting prefix is not a complete replacement for the source route.
- Low demand without PV: 26 source segments form two valid old-style windows.
  Both fit the old contract. On replay the maximum quarter-end SOC difference
  is about 24.687 percentage points. End SOC changes from 10.000017% to
  16.394717%; home grid import increases from 0.089236 to 0.513332 kWh.

The reason is functional: a sustained charge replaces passive home discharge
that the original segmented route expected during the remainder of those
quarters. Equal assigned charge energy does not imply an equal SOC route.
Preparation is modelled optimistically as normal passive operation for two
minutes; any forced-zero transition still needs later modelling/validation.

Conclusion: old window formation is a useful reference, but transplanting it
into the Bridge does not preserve Alpha52's validated segmented projection.
A plan-aware action-window design must be discussed before changing chapter 5.
No minimum duration, pause, new planner policy, release or HA modification has
been approved by this experiment. Existing GitHub build/publication permission
remains valid within the agreed scope; this finding is not release readiness.
