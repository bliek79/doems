# P2 — Verified original Alpha84 coordinator connection contract

## Source of truth
- Original released source: `bliek79/dummy-os-anker-ems` tag `0.0.1-alpha.84`, `custom_components/anker_ems/coordinator.py`, `execution.py`, `authority_fence.py`.
- DOEMS development: draft PR #107.
- This document does **not** authorize physical execution or changes to the installed original EMS.

## Verified blocking fact
Original `AnkerEmsExecutionController.async_execute_automatic_plan(expected_identity=None)` first calls `await self._coordinator.async_refresh()`, and then reads `self._coordinator.data`. The original coordinator's `_async_update_data` derives its *own* planner bridge, syncs and hands off *its own* Plan Store, evaluates *its own* Scheduler, then runs original Pre-start, Safety Guard, execution handoff, final revalidation, mode-switch preview, and execution shadow. A DOEMS read-only projected dict is **not** the original coordinator's state and cannot be treated as its execution input.

## Original live refresh sequence (source lines 1461–1571)
1. Original planner bundle / metadata.
2. `build_planner_action_bridge(data)`.
3. `self.plan_store.async_sync_automatic_plans(...)`.
4. `self.plan_store.async_handoff_automatic_plans(...)`.
5. `self.scheduler.evaluate(...)`.
6. Refresh `build_planner_action_bridge(data)`.
7. `AnkerEmsPreStartValidator().evaluate(data)`.
8. `self.safety_guard.evaluate_automatic_handoff(data)`.
9. `self.execution.evaluate_automatic_handoff(data)`.
10. `self.execution.evaluate_final_revalidation(data)`.
11. `self.execution.evaluate_mode_switch_transaction(data)`.
12. `self._automatic_execution_shadow(data)`.

## Safe connection, not a second controller
A future source-selection seam MUST be inside that original coordinator refresh, at the original planner/bridge -> Plan Store handoff boundary and **before** original scheduler/prestart chain, not by writing to `coordinator.data` after refresh, monkeypatching refresh, or invoking the physical controller with synthetic safety flags. The seam must accept exactly one authenticated current DOEMS R6-published candidate set, with generation/signature/identity and validity proof; honor manual priority; refuse stale, missing or duplicated candidates; and preserve the complete unchanged original downstream chain. On rejection do not promote/do not actuate.

## Required approval gates before wiring physical execution
- Do not modify the installed Alpha84 integration or its normal control behavior in this PR.
- A source-mode switch must explicitly and persistently distinguish legacy planning from DOEMS planning. The original plan path remains the default; no mixed planner writes.
- Demonstrate no second physical controller and one writer at a time, including across restart/failure and rollback. Authority Fence stays authoritative.
- The original `async_execute_automatic_plan` must still refresh and consume original coordinator-generated evidence: `auto_shadow_execution_permitted`, `auto_final_revalidation_safe`, `auto_mode_switch_preview_ready`, selected plan origin/identity and physical control readiness.
- Preserve original 0 W guard, 60-second stable-control gate, final live revalidation, measured power limit, monitored stop, audit, retry/abort and restart recovery.
- Keep DOEMS execution master OFF until explicit separate authorization and validated integration tests/hardware review.

## Status
**Missing actual source-selection seam. Not physically wired.** Current DOEMS P2 code validates via read-only snapshots only. No release or live takeover is authorized by this document.
