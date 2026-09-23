# DOEMS 0.1.0-alpha.15 - Step 12.4 Automatic Execution Gate

## Scope
Step 12.4 adds the final fail-safe permission gate between the live-green Step 12.3 chain and the later physical Execution Controller.

## Added
- Central Automatic Execution Gate with statuses:
  - idle
  - blocked
  - ready_disarmed
  - armed_ready
- Explicit DOEMS Automatic Execution switch.
- Fail-safe restart policy: the arm always starts OFF after integration setup/reload and is not restored automatically.
- Stable planner identity and selected-slot continuity checks.
- Safety-chain checks for Prestart, Safety Handoff, Execution Handoff, Final Revalidation and Mode-Switch Preview.
- Execution-buffer recovery exception only for allowed safety charging.
- Manual/legacy override priority.
- Trading execution gate requiring known day-ahead prices.
- Scheduler observability for price_sources and all_prices_known.
- Central gate blockers, warnings and per-check diagnostics.

## Safety boundary
Step 12.4 remains non-actuating:
- the arm is only a permission bit for the later Step 12.5 controller
- execution_controller_invoked=false
- service_calls_performed=false
- physical_execution_authority=false
- physical_execution_enabled=false
- no mode, direction, setpoint or lifecycle-active write is performed
- no Home Assistant control service is called

Even when the gate reports armed_ready and execution_permitted=true, Step 12.5 is still absent and no physical command is issued.

## Next
Step 12.5 remains closed: Execution Controller, runtime safety, safe-return and audit are not part of this release.
