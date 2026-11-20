# DOEMS v0.3.0-alpha.8.8 — H5–H8 baseline repair candidate

**DEVELOPMENT ONLY. This is NOT a published pre-release, NOT approved for
HACS or Home Assistant installation. Do not merge to main.**

This branch is based on the already published v0.3.0-alpha.8.7 and targets
two independently reproduced foundational defects without redesigning
Alpha84's economic or safety policy:

1. Restore original Alpha84 three-slot terminal lifecycle reuse across both
   Plan Store assignment and the durable Store. Cancelled/empty manual slots
   no longer permanently block the next two valid automatic actions. Manual
   pending and active plans remain protected; identities and Store field IDs
   remain intact.
2. Fix premature rounding of 15-minute source flow values before they cross
   the Bridge handoff. A 0.0375-kWh quarter is retained as 0.0375 kWh rather
   than 0.037 kWh; original hourly 60-minute output precision remains intact.

This does NOT yet assert that all hourly-vs-quarter safety timing differences
are resolved. CI and live validation are needed before any release.

No device authority, entity IDs, scheduler priority, manual start delay,
or existing release tags are changed. Source-related HA startup performance
issue is tracked separately (GitHub issue #113).
