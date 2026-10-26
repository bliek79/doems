# P2 — Alpha84 execution and safety parity ledger

Reference: `bliek79/dummy-os-anker-ems`, tag `0.0.1-alpha.84`.
Target: DOEMS branch `p2-alpha84-execution-safety-parity`.
Unchanged architectural contract: DOEMS has its own forecast and Manual, Automatic, Combined planning.

**Rule:** Preserve the proven Alpha84 safety and physical execution behavior.
Do not substitute an unproven new implementation for working Anker behavior.
No release, HACS deployment, or real battery commands from this branch.

| Alpha84 proven component | DOEMS state before this P2 follow-up | Acceptance evidence needed |
| --- | --- | --- |
| Persistent legacy single-writer `authority_fence.py` | DOEMS has boolean authority/exclusivity gates but no equivalent verified takeover | Closed old fence, no in-flight writes, confirmed new exclusive ownership, restart-safe rollback, races tested |
| `execution.py` charge/discharge controller | DOEMS adapter/controller structurally different, runtime wired with authority OFF | Scenario-by-scenario execution parity and physical observation |
| `physical_test.py` timed tests | Separate physical-test controller/services missing | Preserve bounded charge/discharge tests, timeout, safe stop and restart recovery |
| `prestart_validator.py` and `safety_guard.py` | DOEMS scheduler/adapter gates differ | Explicit parity matrix of blockers, freshness, reserves, mode, SOC and command-readback |
| Automatic mode-switch and safety return | Both have control-path staging | Prove 60-second stability, timeout/failure rollback, zero readback, self-consumption and delayed readbacks |
| `execution_status_reset.py` | Pure policy ported; DOEMS uses legacy live safety reader | Prove no acknowledgement on any unavailable/ambiguous/active legacy state; retain audit |
| Automatic audit and plan-versus-actual | DOEMS combined status attributes, separate Alpha84 audit missing | Preserve requested/applied power, actual energy/power, timestamps, stop reason and retained audit |
| Legacy HA services: start/stop test, start selected, start now, stop execution, stop all | Not equivalently publicly implemented | Verify user-facing control parity without bypassing gates |
| Old DOEMS safety and execution diagnostics | New DOEMS consolidates states | Map every essential indicator to independently auditable entity or explicit attributes |

## Current stop conditions

1. Do not turn on physical authority while the legacy writer may still act.
2. Do not claim P2 is fully equivalent while any row above remains unverified.
3. CI passing proves only tested software paths, never physical transfer.
4. Preserve published `v0.2.0-alpha.9.6`; no tag overwrite.
5. Any proposed new entity identifiers require explicit user approval.

## Initial follow-up improvement

The master switch now refuses to represent ON unless the separate authority,
adapter authorization, bridge authorization and bridge exclusivity are all
present. In released Alpha9.6 all are intentionally not granted, so the
control remains effectively OFF. This is a safety hardening step, *not*
a completed handoff or new live execution capability.


## Point 1 verification update (2026-10-26)

- DOEMS now invokes the **original Alpha84 Safety Guard** against a projected
  Combined-selected slot and current original-coordinator telemetry.
- The original Alpha84 final validator is also invoked; it cannot be replaced
  by a DOEMS-calculated approval.
- A mismatching old scheduler plan, missing original safety evidence, or
  negative guard decision blocks, with regression coverage.
- **Not yet green for functional parity**: Alpha84's original
  `SafetyGuard.evaluate` expects `third_party_control`, while the
  automatic handoff path checks readiness *before* the mode switch.
  Verify both phases through the original `evaluate_automatic_handoff`
  and original pre-start checker instead of treating this post-mode guard as
  sufficient proof. DOEMS' new plan identity also does not inherently
  exist in Alpha84's scheduler. Any approval must be derived from real
  matching live state, not fabricated flags.
- No physical authority granted; no live battery tests performed.
