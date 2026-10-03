# DOEMS 0.1.0-alpha.35 - Sequential Plan72 Safety Exception

## Classification

Alpha35 introduces the **second explicitly authorized functional exception** to the Anker EMS 0.0.1-alpha.76 copy.

The frozen Alpha76 planner sources remain present and byte-identical for audit. Production Plan72 now uses an isolated derivative of `planner_72h.py` in which only the known optimistic safety-precharge defect is corrected.

This exception is deliberate and permanent. It must not be removed by a later "100% copy" cleanup.

The two authorized deviations are now:

1. Canonical DOEMS host/runtime adapters required to preserve Alpha76 behavior on the DOEMS/Home Assistant runtime, including alpha33 runtime serialization and alpha34 verified setpoint handoff.
2. Alpha35 sequential Plan72 safety planning because the original Alpha76 pre-estimator can publish a future execution-reserve requirement that its own projected SOC does not actually reach.

## Live finding

The old-versus-new dashboard on 3 October 2026 exposed the defect directly:

- the Alpha76-based reserve profile reached approximately 100%;
- DOEMS projected SOC remained materially below that execution reserve;
- the Plan72 result could still be marked valid because Alpha76 treated `auto_plan_72h_valid` separately from `auto_plan_72h_execution_buffer_safe`.

This is not a dashboard defect. The graph reads `soc_end`, `reserve_floor_soc` and `execution_reserve_floor_soc` from the same Plan72 result.

## Root cause

The Alpha76 function `_planned_dynamic_safety_charge_by_hour()` estimates each later reserve deadline by restarting from the original start SOC, adding forecast solar and earlier planned safety charging, but not subtracting intervening home discharge.

The later sequential simulation *does* consume battery energy for the home. The pre-estimator and published SOC path can therefore disagree.

The same defect was previously identified and fixed in the earlier Dummy OS Energy native planner. Alpha35 deliberately ports that proven correction principle back into DOEMS.

## Alpha35 behavior

- Keeps the frozen Alpha76 `energy_need.py`, `planner_preview.py` and original `planner_72h.py` byte-identical for source audit.
- Activates an isolated `planner_72h_sequential_safety.py` derivative through the DOEMS compatibility adapter.
- Replays the safety plan against one continuous SOC path.
- Includes intervening home use, solar, charge efficiency, discharge efficiency, capacity and configured power limits.
- Protects accepted safety energy until its reserve deadline.
- Uses backward reachability so existing battery energy cannot be spent when maximum charge power would no longer restore a coming reserve.
- Allocates useful safety energy to the cheapest technically usable hour(s) at or before each deadline.
- Treats upstream Alpha76 Preview safety hours as advice; the replay-validated safety plan is authoritative.
- Keeps safety ahead of trade.
- Fails closed when the final projected SOC cannot meet its own execution reserve.

## Hard invariant

For a Plan72 result published as valid and safe:

`soc_end >= execution_reserve_floor_soc`

for every Plan72 row, allowing only the existing rounding tolerance.

An infeasible reserve deadline is now reported as `auto_plan_72h_status=infeasible`, `auto_plan_72h_valid=false`, with `auto_plan_72h_first_execution_breach` and safety replay diagnostics.

## Unchanged Alpha76 behavior

Alpha35 does not change Scheduler, Plan Store, manual priority, Automatic Execution arm semantics, Prestart, Safety Guard, Action Controller, Execution Controller, 10 W setpoint monitor, physical-test behavior, planned-energy stop, target-SOC stop or safe return.

The native DOEMS forecast architecture remains 15 minutes / 72 hours / 288 slots with the existing compatibility transport into the Alpha76 decision foundation.

## Live validation after install

After installing alpha35:

1. compare the same old-versus-new Plan72 view;
2. verify the reserve peak and projected SOC no longer contradict each other;
3. verify `auto_plan_72h_execution_buffer_safe=true` only when every row has non-negative execution headroom;
4. then continue the already-open physical Step-4 execution validation.
