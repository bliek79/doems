# DOEMS 0.2.0-alpha.7.1.12 — R7 Scheduler, Safety & Prestart

**Scope:** Reset line R7; R0–R6 remain the accepted baseline. The release does **not** open R8 and does **not** enable physical battery execution.

## New in R7

- One deterministic, non-actuating Scheduler over the **three existing R6 Plan Store slots**. Scheduled due actions are selected by earliest start time and then slot number; direct Manual pending actions follow.
- Read-only Safety Guard checks for the actual configured battery observation contract, fresh data, power limits, SOC direction and the existing R5 hard reserve floor.
- Authoritative Prestart is evaluated only for a due automatic concept inside its own start window, after the complete current R5/Combined generation and R6 slot synchronization are confirmed.
- Approved **R7-D1 / option B** and **R7-D2**: automatic \`concept → pending\` only during \`start_time ≤ now ≤ start_time + max_start_delay_min\`, after current Safety/Prestart pass.
- The Plan Store transition is identity-, signature-, origin-, lifecycle-, timestamp- and window-guarded. It preserves \`origin=automatic_72h_planner\` and \`planner_identity\`, persists the new lifecycle, and does not trigger Manual/R5 recomputation.
- New read-only diagnostic sensor: \`sensor.doems_r7_scheduler_status\` (selection, start-window schedule, Safety and Prestart statuses/blockers, last promotion). No additional helpers or slots.
- Tests cover selection order, start-window boundaries, blocked/fresh inputs, reserve handling, Manual ownership, persistent guarded promotion, duplicate writes, R6 expiry and physical-execution invariants.

## Frozen architecture / safety

- Native quarter resolution stays **15 minutes / 72 hours / 288 slots**; no new optimizer or change to R5 policy.
- Manual wins over Automatic. A manually edited slot cannot be promoted by R7.
- Existing R6 rolling replanning continues until an automatic start window; R6 cleanup releases expired automatic pending or concept proposals.
- This is a **software-only pending status**. Scheduler/Safety/Prestart do not dispatch commands, change operating mode, arm automatic execution, operate Modbus, or call a Home Assistant battery service.
- \`physical_execution_enabled=false\` and \`execution_authority=false\` remain explicit.

## Validation and installation

GitHub Actions runs the complete regression suite, compile/JSON checks, and R7-specific acceptance checks before publishing the release. After installing, check \`sensor.doems_r7_scheduler_status\` and the existing \`sensor.doems_plan_{1,2,3}_status\` entities. A successful CI/release does **not** by itself establish R7 LIVE GROEN; that status requires separate Home Assistant live validation and user acceptance.

DOEMS \`0.2.0-alpha.7.1.11\` remains the rollback release. Solar Actual Quarter and the R0–R6 contracts are unchanged.
