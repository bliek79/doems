# DOEMS 0.2.0-alpha.7.1.13 - Scheduler Status Identity Fix

**Scope:** naming and entity-registry correction only; same R7 Scheduler, Safety, Prestart and guarded software-only \`concept -> pending\` behavior as 0.2.0-alpha.7.1.12. No R8 implementation and **no physical battery execution**.

## Permanent Home Assistant identity

The public Home Assistant sensor now follows the established DOEMS naming rule: identify functions, **not development phases**.

- Public entity: \`sensor.doems_scheduler_status\`.
- Unique ID and suggested object ID: \`doems_scheduler_status\`.
- Display name: \`DOEMS Scheduler Status\`.
- Read-only dashboard example: \`examples/doems_scheduler_status_card.yaml\`. Its title and entity reference are phase-free.

**Existing installations:** on integration setup, the targeted entity-registry migration upgrades the former \`doems_r7_scheduler_status\` unique ID and \`sensor.doems_r7_scheduler_status\` entity ID to the permanent names. It is idempotent and does not create a duplicate. If the permanent target already exists, it takes precedence and the temporary old entry is retired. A foreign entity-ID collision fails explicitly without silently renaming another integration's sensor.

**New installations:** the permanent identity is registered directly, without temporary R7 names.

The earlier name was not consistent with the previously accepted naming contract. Phase labels remain valid in internal source, historical documents and CI tests, but not in public sensor names, IDs, dashboard labels or functional product names.

## Unchanged contracts

- Existing three R6 slots; Manual origin always wins.
- Exactly 15 minutes / 72 hours / 288 forecast quarters.
- R7-D1/B and R7-D2 status-promote gate unchanged.
- Read-only Scheduler/Safety/Prestart; no extra helper or planner.
- \`physical_execution_enabled=false\` and \`execution_authority=false\`.
- Solar and frozen R0-R6 logic unchanged.

## Verification and next steps

GitHub Actions validates full regression tests and packaged artifact integrity before publishing. After installing, verify **\`sensor.doems_scheduler_status\`** and its diagnostic attributes, the three existing plan status sensors, and the continued physical execution block.

Technical publication is not R7 LIVE GROEN. Home Assistant live validation and the user's explicit acceptance remain necessary.

Rollback release: 0.2.0-alpha.7.1.12; previous user-confirmed live release before R7 was 0.2.0-alpha.7.1.11.
