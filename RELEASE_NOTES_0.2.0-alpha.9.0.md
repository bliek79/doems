# DOEMS 0.2.0-alpha.9.0 — R7 baseline release

Official GitHub release (not marked prerelease) of the proven R7 code baseline from 0.2.0-alpha.7.1.16.

No R8 implementation is included. Manual/Automatic/Combined planner behavior, scheduler, safety and native 15-minute / 72-hour / 288-slot architecture are unchanged from 7.1.16. Only version and release metadata have changed.

Original baseline: commit a89efb2697e01995556a215a4a79e5eed3ff2334.

## Original R7 release notes

# DOEMS 0.2.0-alpha.7.1.16 — Manual Concept Expiry Cleanup

**Scope:** user-approved Manual lifecycle completion after identifying an expired `concept` occupying Plan 2. This is a targeted extension of the existing three-slot Plan Store, not a new planner or R8 execution feature.

## Behavior
- A **Manual planned concept** with a valid charge/discharge action, timezone-aware start time and valid configured start margin expires **strictly after** `start_time + max_start_delay_min`. The exact deadline remains valid.
- Incomplete Manual concepts (no action or no start time) and `direct` concepts are preserved. Malformed dates or start margins block cleanup safely rather than discarding user input.
- Existing Manual `pending` expiry semantics, their audit reason and valid-until-deadline behavior remain unchanged.
- A newly expired Manual concept is cleared from the active slot, and an audit event is persisted with `previous_lifecycle_status: concept`, `reason: manual_concept_start_window_expired`, and `released_reason: manual_concept_expired_released`.
- The existing Plan Store persistence and Manual lifecycle timer perform cleanup on startup, at the timer boundary, and after Manual edits. No new sensors or helpers.
- The R6 Automatic bridge can immediately reuse the cleared slot on its next normal reconciliation. A still-valid Manual slot keeps absolute priority; R6 never overwrites Manual.
- This logic does not run on Automatic-origin proposals. Automatic expiry and R7's non-actuating Prestart gate remain unchanged.

## Safety and architecture
- Exactly **15 minutes / 72 hours / 288 native forecast slots**; exactly three existing Plan Store slots.
- Manual minimum duration remains 30 minutes; R6 automatic minimum remains 15 minutes.
- No new actuator, scheduler, Home Assistant entity, helper, renaming, or dashboard change.
- **Physical battery execution remains disabled**; R8 remains closed.

## Validation
Full CI/regressions and additional expiry-model and Plan Store integration tests must pass before release publication. Regression tests cover exact expiry boundaries, old pending compatibility, incomplete/invalid/direct draft preservation, automatic ownership, persistent expiry events, restart/idempotence and subsequent R6 reuse of the freed slot.

After Home Assistant installation, confirm in `sensor.doems_plan_2_status` and `sensor.doems_manual_plan_lifecycle` that the stale Manual concept has an expiry audit event, and that Automatic can use the freed slot on the next normal cycle. No forced battery action is needed.

**Release success does not mean R7 LIVE GROEN.** The R7 live-validation status remains open pending the user's separate validation and acceptance. R0–R6 remain frozen and LIVE GROEN.

Rollback: `0.2.0-alpha.7.1.15`.
