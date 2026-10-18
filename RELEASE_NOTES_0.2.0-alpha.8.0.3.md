# DOEMS 0.2.0-alpha.8.0.3 — R8 execution shadow

Based on original reset route (6 October 2026), not on the later invented R8-A readiness contract.

Adds `sensor.doems_r8_shadow_execution` to observe the existing R7-selected plan and prepare the semantic action in shadow, following the historical Anker EMS action-controller principle. Possible states: `geen_actie`, `geblokkeerd`, `voorbereid_shadow`. Attributes expose selected slot/origin, action, power, target SOC, maximum runtime, blockers and explicit false execution authority.

R7 model/runtime, all three planners, Plan Store and lifecycle are source-code unchanged. No battery service calls, mode changes, retry actuation or physical execution. R8 does not select or mutate plans. R7 remains authoritative.

This release restores the **shadow preparation stage**, not the entire historical physical execution state machine. Physical execution requires separate explicit approval and later fail-safe validation. A successful CI is not live Home Assistant validation.
