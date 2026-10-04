# DOEMS 0.1.0-alpha.36 - Best-of-Both Planner

## Purpose

Alpha36 brings the latest proven planner improvements from the old Dummy OS EMS
line into DOEMS without rolling back the stronger DOEMS safety and runtime
architecture.

The release combines:

- Anker EMS Alpha80/81 Cheapest Energy Safety planning;
- DOEMS Alpha35 sequential Plan72 safety authority;
- native DOEMS 15-minute / 72-hour / 288-slot input;
- Alpha33 serialized planner/execution snapshot publication;
- Alpha34 verified physical setpoint handoff;
- the existing frozen Alpha76 Scheduler, Prestart, Safety, Action Controller,
  Execution, restart/recovery and safe-return behavior.

## Alpha80/81 economic improvements

Alpha36 ports the Alpha80 Energy Need and Planner Preview policy and keeps their
economic semantics:

- a low-solar horizon remains planable even when no two-hour usable-solar block
  exists;
- the complete rolling 72-hour route is considered;
- when the projected route would fall below the 5% technical minimum + 7%
  software reserve planning target, all technically reachable charge windows
  before the deadline are evaluated;
- the cheapest reachable import window wins;
- an earlier more expensive window is used only for the bridge energy needed to
  safely reach a later cheaper window;
- a cheap window may charge close to 100% when later forecast household demand
  requires that stored energy;
- solar remains first priority and trade remains subordinate to household safety.

The Alpha80 Energy Need and Planner Preview source ports are regression-locked
against the published Alpha81 policy hashes after the isolated DOEMS relative
import adaptation.

## DOEMS Alpha35 safety remains authoritative

Alpha36 does not replace the Alpha35 safety correction with the older Alpha80
Plan72 safety estimator.

The Alpha80 economic Plan72 candidate is accepted only when every projected
hour also satisfies the Alpha35 sequential execution-reserve path. The Alpha35
guard continuously accounts for intervening household use, solar, efficiency,
capacity, charge/discharge power limits and reserve deadlines.

If the Alpha80 economic route violates that stricter execution-reserve
invariant, Alpha36 publishes the Alpha35 sequential repair instead and marks the
result as an explicit safety override.

Hard invariant for every valid/safe Alpha36 plan:

`soc_end >= execution_reserve_floor_soc`

within the existing rounding tolerance.

An infeasible reserve deadline remains fail-closed.

## Alpha81 multi-rate runtime completion

DOEMS already contained the main Alpha81 multi-rate principles. Alpha36 keeps
the DOEMS 5-second fast execution/safety path and adds the missing request-level
coalescing semantics:

- freeze one immutable planner input before heavy compute;
- compare signatures against published, active and pending requests;
- do not create a new generation for a duplicate/no-op source callback;
- keep only the newest pending generation;
- discard a stale worker result when newer material input arrives;
- keep the last valid published bundle available while the next generation
  computes;
- add one-shot `start_critical` replanning when a new automatic planner action
  becomes due;
- keep Energy Need + Planner Preview + Plan72 atomic as one published bundle.

Heavy planning remains off the Home Assistant event loop. Fast execution,
control-path and SOC telemetry refreshes do not run the heavy planner.

## Unchanged physical control

Alpha36 does not rebase or redesign physical execution.

Unchanged:

- Plan Store and Scheduler;
- manual priority;
- Prestart and Safety Guard;
- Automatic Execution arm semantics;
- Final Revalidation and mode-switch preview;
- Alpha76 Execution Controller lifecycle;
- 0 W guard and safe return to `self_consumption`;
- Alpha34 setpoint confirmation within the existing 10 W tolerance;
- restart/recovery behavior.

The Alpha77 legacy authority-fence module is not copied into DOEMS because it
belongs to the old-controller coexistence/cutover path. During physical DOEMS
validation the old Anker EMS must remain quiescent so there is only one physical
writer.

## Recorder and diagnostics

The existing DOEMS 10 KiB Recorder-bound attribute budget remains enforced.
Large plans, checks and traces remain unrecorded. Alpha36 adds only compact
policy/runtime provenance and signature diagnostics.

## Validation gates

Alpha36 must pass before publication:

1. frozen Alpha76 execution/Scheduler/Safety source parity;
2. Alpha33 snapshot serialization regression;
3. Alpha34 verified setpoint handoff regression;
4. Alpha35 sequential safety regression;
5. Alpha80 low-solar / cheapest-window / bridge-energy / near-100%-charge policy scenarios;
6. Alpha36 safety-superiority and infeasible fail-closed scenarios;
7. native multi-rate no-heavy-work-on-fast-path checks;
8. published/active/pending signature coalescing and start-critical contract;
9. Recorder 10 KiB budget;
10. the complete DOEMS pytest suite, compile and JSON validation.

## Live validation after install

After installation, first validate several natural quarter cycles with the old
Anker EMS quiescent. Compare SOC path, reserve, execution reserve, safety energy,
selected price windows, bridge energy, Solar Charge Delay, trade and the next
planned action.

Only after that planner/runtime validation is green should the open physical
Step-4 gate be completed:

Automatic Execution arm -> Scheduler start-ready -> start-critical/final
revalidation -> `third_party_control` -> direction/power -> verified setpoint
handoff -> execution monitor -> stop -> 0 W -> `self_consumption`.
