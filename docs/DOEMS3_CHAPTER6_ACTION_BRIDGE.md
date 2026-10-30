# Chapter 6 — Automatic Action Bridge

Base: `v0.3.0-alpha.5.3`, `ffafa97c6008bb2ccd5064f346e3a2d6cc0935ad`.
Development branch: `doems3-action-bridge-alpha53`. First release: `v0.3.0-alpha.6.1`.

## C.6.3 Architecture and proven reference

The original Anker EMS `0.0.1-alpha.84` `planner_action_bridge.py` separates forced grid actions from passive self-consumption, processes candidates chronologically and keeps a valid prefix before a truly invalid action. Alpha84 explicitly removes the blanket post-limit hold: a feasible capped charge retains its shortfall without suppressing the third later candidate. Original `plan_store.py` owns persistence, manual edits, future pending reconciliation, active/due protection and lifecycle.

DOEMS keeps that division. Alpha 5.3 now supplies the actual simulated action windows. Chapter 6 never regroups raw segments, computes average power, shifts windows, subtracts preparation again, optimizes prices or simulates SOC. The earlier Alpha5.2 Bridge draft is historical research, not the base of this release. Old hourly thresholds and mixed-purpose grouping are not transplanted onto the native quarter contract.

## C.6.4 Input contract

One atomic Plan72 runtime snapshot: `valid`, `status`, `reason`, `reserve_satisfied`, `start`, `end`, `horizon_hours=72`, `slot_count=288`, `timeline`, `battery_parameters`, `plan_generation`, `input_fingerprint`, `calculated_at`, `action_window_contract=quarter_windows_v1`, `action_windows`, `action_window_count`.

Windows retain their exact start, power start, end, 15-minute to 12-hour envelope, two-minute zero-power preparation, 10-W setpoint steps with 100-W minimum, requested/projected power durations, battery AC energy, separate flows, start/reached/command/end SOC, limitation and reason. These are existing Plan72 rules, not new Bridge policy.

The Bridge indexes each window ID's exact preparation/powered segments, checks energy/power/SOC and source signature and verifies horizon end-SOC separately from reached target. The public `target_soc` is the reached last-powered SOC; `command_target_soc` is retained as the planner's internal cap/floor. A candidate command replay test proves the public targets preserve the source route for safety and paired trade.

All timestamps must be timezone-aware and are normalized to UTC for comparison. A snapshot must cover the current next quarter and have a current calculation timestamp. Missing/malformed global coverage or unknown explicit windows clears the preview. A malformed individual window remains visible as invalid and holds its successors.

## C.6.5 Output for chapter 7

`doems_action_bridge_v1` contains all `candidates`, their `eligible_candidates`, `slot_preview` (first three eligible, assuming free capacity) and `overflow_candidates`. It reports calculation status/validity/reason, invalid and held counts, valid limited-charge count and raw shortfall in total battery AC kWh. Bridge validity and per-candidate validity are distinct from future permission to execute.

Each candidate retains the source window fields and adds `action_type` (`safety_charge`, `trade_charge`, `grid_discharge`), `execution_mode=scheduled`, `valid`, `validation_reasons`, `validation_warnings`, `selection_status`, `source_segments`, `explicit_grid_energy_kwh`, `capacity_limited`, `feasible_energy_kwh`, `battery_parameters`, stable `planner_identity`, full-content `planner_signature`, `source_window_id`, `source_planner_identity`, `source_planner_signature`, `source_plan_generation`, `source_input_fingerprint` and `source_calculated_at`.

Identity follows the original purpose + source anchors + nominal end convention. Generation/provenance and internal source window IDs are excluded from the actionable revision signature. Changed times, power, SOC, energy or flow content revise the signature. Identity is not a universal overlap/deduplication guarantee: chapter 7 must also protect active plans and use time overlap as the original does.

A limited but coherent source charge keeps its exact feasible action and shortfall. The Bridge does not create another reduced-energy route. Truly invalid actions cut the prefix. On limited or reserve-unsatisfied source routes, economic candidates are held; coherent safety candidates remain observable.

No slot number, manual availability, overwrite permission, pending lifecycle or late-start allowance is assigned here. Chapter 7 must preserve hard end, preparation and source generation when adding those controls; an original ten-minute start delay cannot silently extend a native action into a later price window.

All output remains `observational_only=true`, `execution_enabled=false`, `physical_execution_authority=false`; Plan Store writes and Scheduler handoff remain disabled.

## C.6.6 Files and entities

New calculator/runtime: `planner_action_bridge.py`, `planner_action_bridge_runtime.py`. Minimal setup/unload and entity registration in `__init__.py`, `sensor.py`, `binary_sensor.py`. Both Plan72 modules and both Energy Need modules remain byte-for-byte Alpha5.3 sources.

| Entity | State | Detail |
|---|---|---|
| `sensor.doems_ems_action_bridge_status` | idle/ready/limited/blocked/invalid | Reason and source generation |
| `binary_sensor.doems_ems_action_bridge_valid` | on/off | Calculational eligibility, never start permission |
| `sensor.doems_ems_action_candidates` | All candidate count | Candidate validation and full provenance |
| `sensor.doems_ems_action_slot_preview` | Preview count, 0–3 | Hypothetical preview and overflow count |

The original Preview Status/Decision/Reason describe a separate planner preview. They are not copied as an extra planning layer. Large candidate/preview payloads are excluded from Recorder. Existing 74 DOEMS entities retain registration; expected enabled total is 78. Example: `examples/action_bridge_validation_card.yaml`.

## C.6.7 Verification and release

Directed tests cover real Alpha5.3 safety and paired trade, exact command replay of the full route, bounded-charge third-candidate recovery, fourth-candidate overflow, first/middle invalid prefix, no double preparation, mixed PV/grid/home energy, negative export, malformed/nonfinite data, signature integrity, stable identities, generation changes, current-quarter rejection, DST and listener/unload/source-loss behavior without physical services.

Release controls: `validate_action_bridge_release.py`, `build_action_bridge_release.py`, `publish_action_bridge_release.py`, and `.github/workflows/doems3-action-bridge.yml`. Full suite on Python3.12/3.13; no existing tag/release overwrite; package, checksum and provenance on one exact tested commit. Main is not changed. Actual publication results are recorded after execution, never inferred from this plan.

## C.6.8 Live validation still open

After HACS installation: verify four new entities, matching Plan72/Bridge generations, one candidate per source window, unchanged power/times/energy/target, first three preview plus fourth overflow where present, natural SOC replan replacement and invalidation/recovery on actual source change if safely observable. No forced physical battery test is required for this chapter. Chapter5 economic assessment and later physical validation remain open.
