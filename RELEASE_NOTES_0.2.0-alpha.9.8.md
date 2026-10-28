# DOEMS 0.2.0-alpha.9.8 — P2 plan slot reuse observation

This prerelease packages the validated P2 draft branch for **observation only** in Home Assistant.

- Fix automatic plan slots becoming permanently non-reusable after `automatic_proposal_cleared`.
- Add regression coverage that a cleared automatic slot accepts a new eligible proposal while user-owned Manual slots remain protected.
- Fix in-memory persistence isolation of two P3 plan-store integration tests.
- Retry non-actuating registration of the already-loaded original Dummy OS Anker EMS controller and expose `original_controller_registration` in DOEMS Combined Execution Status, including while idle.
- Retain the earlier Alpha84 Pre-start Validator / Safety Guard observation and DOEMS R6 plan-lineage guards.

**Safety / acceptance:** DOEMS physical authority and execution remain OFF. Dummy OS EMS continues to control the battery. This release does not approve a physical handoff, does not replace the proven Anker execution controller, and is not proof of end-to-end live safety. Inspect three DOEMS Plan Status sensors, Scheduler Status, Combined Execution Status and original controller registration without enabling DOEMS execution. Preserve the existing release tags and keep main unchanged.
