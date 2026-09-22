# DOEMS 0.1.0-alpha.10 - Step 12.1 Control-path Readiness

## Scope

Alpha10 builds only **Step 12.1 - Control-path contract + read-only readiness**.

The implementation copies the current working two-stage control-path readiness behavior from `dummy-os-anker-ems` into the standalone DOEMS integration. Forecast, Energy Need, Plan72, Plan Store, Scheduler and Safety/Prestart remain the existing DOEMS-native layers.

## Added

- `custom_components/doems/ems_control_path.py`
  - read-only mapping of operating mode, action direction and power setpoint;
  - exact pre-mode/post-mode readiness split;
  - 60-second stability requirement;
  - source-parity blockers:
    - `operating_mode_unavailable`;
    - `operating_mode_not_stable`;
    - `action_direction_unavailable`;
    - `action_direction_not_stable`;
    - `power_setpoint_unavailable`;
    - `power_setpoint_not_stable`;
  - `awaiting_third_party_control` while post-mode controls are intentionally not required yet.

- Three optional EMS mappings in Options:
  - operating-mode select;
  - action-direction select;
  - power-setpoint number.

The three mappings are optional for upgrade compatibility, but when one is configured the full set is required.

- Live runtime observation and state-change refresh for the configured control path.
- Step 11 Safety now receives the real read-only `control_path_configured` value instead of the former hardcoded false boundary.
- Compact control-path diagnostics on `sensor.doems_ems`.

## Two-stage readiness contract

While the battery is not in `third_party_control`:

- only the operating-mode select must be configured, available and stable for 60 seconds;
- action direction and power setpoint may legitimately be unavailable;
- `ready` means only that it is safe to reach the future mode-switch boundary.

While the battery is in `third_party_control`:

- action direction and power setpoint must also be available and stable for 60 seconds;
- post-mode readiness becomes required.

This readiness does **not** grant execution authority.

## Physical safety boundary

Alpha10 deliberately does not add:

- Action Controller execution;
- Execution Controller;
- mode writes;
- direction writes;
- power-setpoint writes;
- an automatic execution arm switch;
- Home Assistant service calls to the battery;
- physical execution authority.

The runtime continues to publish:

- `action_controller_invoked=false`;
- `execution_controller_invoked=false`;
- `automatic_execution_armed=false`;
- `service_calls_performed=false`;
- `physical_execution_authority=false`.

## Validation

CI must pass:

- Python compile;
- full pytest suite;
- JSON validation;
- Alpha10 release-contract validation;
- Foundation Regression CI.

After installation, Step 12.1 is ready for live shadow validation by configuring the three control-path entities and confirming pre-mode/post-mode readiness without any battery writes.

Step 12.2 and later Step 12 execution layers remain closed.
