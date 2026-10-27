# DOEMS 0.2.0-alpha.9.7 — P2 Alpha84 shadow-validation prerelease

This prerelease packages Draft PR #107 (P2 Alpha84 safety parity) for observation in Home Assistant.

- The real R6 published-plan lineage is checked against the Combined selection, generation, signature, action, power, and target SOC.
- The installed original Alpha84 Pre-start Validator and Safety Guard are invoked on an isolated, non-actuating snapshot.
- Missing, duplicated, modified or stale candidates fail closed. This is a software-validation build, not physical-execution approval.
- The DOEMS EMS master permission must remain OFF; the original Alpha84 controller must retain exclusive battery authority.
- Do not enable two battery controllers. Verify the live original controller, SOC, fresh forecasts, plan identity, safety results and absence of DOEMS actuator commands before acceptance.
- GitHub CI passing does not establish live Home Assistant parity or physical safety.

This prerelease is built from the P2 validation branch only. Existing tags, releases and main are not modified.
