# DOEMS 0.2.0-alpha.9.9 — original Anker EMS safety observation

This P2 prerelease adds non-actuating visibility for the original Anker EMS safety path to the existing `DOEMS Combined Execution Status` sensor.

- Add `original_safety_observation` for no selected plan, waiting scheduler safety, original-controller validation, and fail-closed blocked outcomes.
- Continue using the proven original Alpha84 Pre-start Validator, Safety Guard and final revalidation through read-only inspection; no replacement safety algorithms.
- Retain the previously verified alpha.9.8 automatic slot reuse fix, original Anker controller registration diagnostics, and Manual priority.

**Safety:** Dummy OS EMS remains the sole live battery controller. DOEMS physical authority remains disabled. No physical takeover, battery commands or live safety parity are approved by this release. Existing releases and `main` remain untouched. Validate in Home Assistant only after CI and immutable release publication succeed.
