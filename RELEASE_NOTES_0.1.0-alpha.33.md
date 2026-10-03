# DOEMS 0.1.0-alpha.33 - Alpha76 runtime serialization adapter

## Classification

This release does **not** change copied Anker EMS alpha76 planner, Scheduler, Safety, Action Controller or Execution semantics.

The live Home Assistant test on 3 October 2026 showed that the native DOEMS multi-rate host runtime could publish overlapping planner/fast execution snapshots during a manual scheduled mode transition. That host-runtime difference is now classified as a permanent, behavior-preserving DOEMS platform adapter — not as an Anker copy error.

For future parity audits, "100% Anker alpha76 copy" means 100% functional/behavioral parity. The following DOEMS-native adapters remain canonical and must not be removed merely to make the architecture byte-identical to Anker:
- DOEMS domain/product identity
- Dummy OS Data forecast sources
- native 15-minute / 72-hour / 288-slot transport
- 288x15m -> 72x60m compatibility transport
- non-decision-changing observability/performance
- this serialized coordinator-snapshot adapter

## Fix

- Adds one runtime state-publication lock around:
  - heavy planner -> Plan Store -> Scheduler publication
  - fast Scheduler/Safety/Execution refresh publication
- Keeps heavy planner computation off-loop and multi-rate.
- Prevents a valid manual scheduled slot from being observed through an inconsistent host-runtime snapshot while the frozen Alpha76 Execution Controller transitions from self_consumption to third_party_control.
- Adds runtime_snapshot_adapter=alpha33_alpha76_serialized_coordinator_v1 diagnostics.
- Adds regression guards that make this adapter canonical.

## Frozen source behavior remains unchanged

The source-verified Alpha76 modules remain protected by the existing blob-SHA parity guard:
- Execution Controller
- Physical Test Controller
- Scheduler
- Prestart Validator
- Safety Guard
- Action Controller
- Energy Need
- Planner Preview
- Planner72

Manual scheduled execution remains independent of the Automatic Execution arm. Automatic planner execution remains arm-gated exactly as before.

## Live validation status

The original 08:55 manual scheduled charge attempt correctly failed safe before non-zero power handoff, exposing the host-runtime snapshot issue. Alpha33 requires a repeat live validation before Step 4 can be marked green.
