# DOEMS 0.1.0-alpha.7.25 - G6 Step 5C Disarmed Authority Transfer Foundation

## Scope

Alpha7.25 implements the disarmed Step 5C-B foundation defined in the routebaseline. It adds authority-transfer observability and the single-writer contract without giving DOEMS any physical battery authority.

The frozen planning path remains unchanged:

`288x15m -> deterministic 72x60m -> unchanged Alpha76 golden core`

Step 5A and Step 5B remain the proven entry chain.

## Added

- Step 5C disarmed authority state builder.
- Optional read-only mapping for the legacy `Automatic Execution` switch.
- Optional read-only mapping for the legacy authority-fence diagnostics sensor.
- Central Step 5C diagnostics on `sensor.doems_ems_shadow`.
- Explicit authority model with current owner `anker_ems`, legacy fence observation and DOEMS write fence permanently closed.
- Separate visibility of:
  - legacy Automatic Execution state;
  - legacy manual mode;
  - legacy write fence;
  - legacy in-flight calls;
  - legacy quiesce state;
  - zero-power observation;
  - safe-return observation;
  - cutover blockers;
  - authority generation and audit counters.

## Important semantic boundary

`Automatic Execution = OFF` means the legacy controller is in manual mode. It is not physical authority release.

A future 5C-C cutover requires the independent legacy physical authority fence to close before `anker_ems` may release ownership.

## Hard safety boundary

This release remains fully disarmed:

- `step5c_live_transfer_enabled=false`
- `step5c_arm_available=false`
- `step5c_service_calls_performed=false`
- `automatic_execution_armed=false`
- `physical_execution_authority=false`
- `doems_write_fence=closed`

There is:
- no Step 5C Home Assistant service call;
- no transfer button;
- no DOEMS arm switch;
- no ownership claim;
- no mode, direction or power write;
- no non-zero physical execution.

## Legacy controller

`anker_ems` remains the only physical battery controller for this release. The companion legacy release provides the write-fence foundation while preserving current operation by default.

## Live validation target

After installation, configure the two optional legacy observation entities and validate through `sensor.doems_ems_shadow` that:
- Step 5C reports `ACTIVE_LEGACY`;
- authority owner remains `anker_ems`;
- legacy Automatic Execution and legacy write-fence state are independently visible;
- DOEMS remains fully disarmed;
- no Step 5C physical service call is possible.

5C-C legacy quiesce/no-owner proof is not part of this release and requires a separate explicit approval.
