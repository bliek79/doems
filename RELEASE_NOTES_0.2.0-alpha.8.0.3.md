# DOEMS 0.2.0-alpha.8.0.3 — R8-A read-only runtime observation

Base: published 0.2.0-alpha.8.0.2. Adds one HA sensor `sensor.doems_r8a_execution_readiness` with the R7-selected slot, origin, validation status, blockers, missing evidence and execution_authorized=false.

R8-A now runs as a Home Assistant observation sensor; it subscribes to the existing R7 scheduler and reads the current plan store. It does not schedule, promote, expire, execute or change plans. R7 and all manual, automatic and combined planner implementation modules remain unchanged.

**Fail-closed:** The current R7 contract does not expose atomic plan revision, final revalidation, handoff or controller-conflict evidence. These are not guessed: the sensor returns `not_validated` until such evidence is available. This is a functional diagnostic R8-A, **not proof of technical execution readiness**, not R8-B and never authorization to actuate.

Validation: complete pytest suite, compileall, JSON check, source diff allowlist, ZIP inspection. Live Home Assistant acceptance, plan transitions and restart persistence still require observations from the installation.
