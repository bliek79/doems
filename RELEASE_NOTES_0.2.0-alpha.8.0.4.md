# DOEMS 0.2.0-alpha.8.0.4 — execution naming correction

Corrects the public entity introduced in 0.2.0-alpha.8.0.3.

- Name: DOEMS Execution Status
- Suggested entity ID: sensor.doems_execution_status
- Unique ID: doems_execution_status
- Status: voorbereid (instead of voorbereid_shadow)
- Public attribute: scheduler_status (instead of r7_status)

No changes to R7 model/runtime, the manual/automatic/combined planners, Plan Store or lifecycle. Physical execution remains disabled. The historical R8 execution state machine is not complete and this release is only for read-only observation. No live Home Assistant validation has been performed.
