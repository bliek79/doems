# DOEMS 0.1.0-alpha.21 - Multi-rate Planner Runtime

## Purpose

Alpha21 keeps the complete Alpha20 cheapest-energy Plan72 policy unchanged while
removing the heavy planner from the five-second execution-shadow cadence.

The production planner policy remains:

- `alpha20_cheapest_energy_safety_v1`
- solar first
- 5% technical minimum + 7% software reserve = 12% planning target
- cheapest technically reachable safety-charge window before a reserve breach
- bridge charge only when needed to reach a later cheaper window
- charging up to 100% remains possible when the 72-hour route requires it
- trade remains secondary to household safety and coverage

## Multi-rate runtime

The runtime now has two explicit rates:

- **Fast execution/safety path (5 s):** reads live SOC, control path and power,
  reevaluates Scheduler, Prestart, Safety, Final Revalidation and Execution
  Shadow against the last valid cached plan. It does not rebuild forecast input
  and does not call the heavy planner.
- **Planner path (15 min / meaningful event):** rebuilds the native 288-slot
  input, runs the unchanged Alpha20 policy off the Home Assistant event loop,
  and publishes a new Plan72 only when the generation is still current.

Planner triggers are startup, native quarter boundary, Energy/Solar/Prices
forecast updates and SOC recovery. Normal SOC changes, plan-store changes,
manual plan edits, arm/disarm and the five-second execution-shadow monitor stay
on the fast path.

## Load protection

Alpha21 adds:

- policy-input signature caching;
- coalescing of closely spaced forecast callbacks;
- single-flight planner execution;
- executor-thread execution for the CPU-heavy planner;
- generation fencing so a stale calculation cannot replace the current plan;
- diagnostics for planner generations, compute count, stale discards and
  same-signature skips.

## Regression gates

Alpha21 adds a byte freeze for `ems_policy_alpha20.py`, exact worker-vs-Alpha20
bundle parity, native-quarter input-signature tests, a 180 x 5-second fast-path
gate, executor/single-flight source checks and generation-fence checks.

The Alpha20 policy source SHA-256 remains:

`cf5f46e7c7cca492f7fb95df062d96db9109f0dc256144885c82efd9ea573eb8`

## Scope

No new public charge type is introduced. G5 remains frozen. Google Sheets stays
validation-only and is never runtime input. Physical execution authority
remains false in DOEMS.

## Live acceptance

After installation, validate first with Anker EMS alpha.78. Confirm Home
Assistant remains responsive across multiple native quarters, the five-second
monitor continues to update safety/execution state, planner compute count grows
only on planner triggers, and DOEMS Plan Archive continues to write one
complete 72-point row per planner cycle.
