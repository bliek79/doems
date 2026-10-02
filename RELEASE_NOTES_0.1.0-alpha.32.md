# DOEMS 0.1.0-alpha.32 - Full Anker Alpha76 EMS Parity Reconstruction

## Scope

This candidate rebuilds the active DOEMS EMS/execution layer from the proven
Dummy OS Anker EMS 0.0.1-alpha.76 behavior instead of adding new DOEMS policy.

Allowed DOEMS-specific differences remain limited to:

- the `doems` domain/product identity;
- Dummy OS Data / native DOEMS forecast sources;
- native 15-minute / 72-hour / 288-slot transport;
- the narrow 288x15m -> 72x60m compatibility adapter;
- non-decision-changing observability and multi-rate runtime performance.

## Reconstructed Alpha76 behavior

- Alpha76 Scheduler semantics.
- Alpha76 Planner Action Bridge semantics, with only the approved one-quarter
  identity-continuity transport exception.
- Alpha76 Prestart, Safety Guard and Action Controller semantics.
- One source-faithful physical Execution Controller, including 10 W setpoint
  tolerance, planned-energy completion, target-SOC completion, runtime monitor,
  audit/history and 0 W -> self_consumption safe return.
- Alpha76 Final Revalidation and mode-switch transaction evaluators.
- Alpha76 Automatic Execution arm semantics with RestoreEntity live_guarded
  restore behavior.
- Manual scheduled execution independent of the automatic arm.
- Alpha76 manual scheduled retry behavior.
- Alpha76 physical charge/discharge test controller and services.
- Alpha76 service/lifecycle behavior for start-now, execute, stop, cancel and
  stop-all.
- Frozen Alpha76 5..100% execution/Scheduler SOC bounds.
- Source-equivalent safety/execution Home Assistant status surface.

## Unchanged

The exact Alpha76 planner files remain byte-identical:

- `energy_need.py`
- `planner_preview.py`
- `planner_72h.py`

No new EMS decision rule, safety blocker, planner policy or physical priority is
introduced in this reconstruction.

## Validation state

Implementation/reconstruction only. Full automatic source-parity and regression
validation is the next gate. Do not merge/release as a completed copy until the
Step 3 parity suite is green.
