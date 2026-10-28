# DOEMS 0.2.0-alpha.9.11

Maintenance release based on v0.2.0-alpha.9.10.

- Rename physical execution master control to **DOEMS Automatic Execution**.
- Rename emergency acknowledgement control to **DOEMS Emergency Stop Acknowledge**; acknowledgement does not activate emergency stop.
- Register both controls under the existing DOEMS device.
- Retain existing unique IDs and migrate existing Home Assistant entity IDs to `switch.doems_automatic_execution` and `button.doems_emergency_stop_acknowledge` when the destination is free.
- No changes to planning or physical battery actuation semantics.

Home Assistant automations and dashboards referencing the previous entity IDs need to use the new IDs after installation. Keep physical execution OFF during upgrade verification.
