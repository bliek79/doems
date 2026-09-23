# DOEMS 0.1.0-alpha.13 - Plan72 Solar Horizon Semantics Fix

## Scope

Alpha13 clarifies the existing `sensor.doems_ems_plan72_solar_horizon` without adding new public Home Assistant sensors.

The change separates three concepts that were previously conflated by the legacy `volledig/onvolledig` status:

- solar forecast coverage across Plan72;
- the next usable solar block seen by the reserve planner;
- the finite end of the Plan72 window.

The underlying reserve, planner, scheduler, safety and controller behavior is not changed. The sensor remains observational only.

## Sensor state

`sensor.doems_ems_plan72_solar_horizon` now uses:

- `ready`: solar forecast covers all 72 Plan72 hours and a next usable solar block exists from Plan72 start;
- `limited`: forecast coverage is partial, or no next usable solar block is found within the current Plan72 window;
- `no_data`: no usable Plan72 solar forecast is available.

A valid night-time forecast value of zero is treated as covered data, not as missing solar data.

## Compact attributes

The existing sensor publishes the following focused diagnostics:

- `forecast_coverage_hours`;
- `forecast_missing_hours`;
- `forecast_coverage_percent`;
- `forecast_complete`;
- `next_usable_solar_available`;
- `next_usable_solar`;
- `hours_until_next_usable_solar`;
- `last_usable_solar`;
- `plan_start`;
- `plan_end`;
- `hours_after_last_usable_solar`;
- `lookahead_limited_by_plan_end`;
- `reason`;
- `observational_only`.

No extra horizon sensors are introduced. The existing `DOEMS EMS Plan72 Missing Solar Hours` sensor is retained for compatibility in this release; its removal is not part of Alpha13.

## Forecast coverage contract

The native 288-slot -> 72-row transport contract now carries a solar-only validity flag. This prevents missing prices or other inputs from being incorrectly reported as missing solar forecast coverage.

## Physical safety boundary

Alpha13 does not add or enable physical battery control.

The existing invariants remain unchanged:

- `automatic_execution_armed=false`;
- `service_calls_performed=false`;
- `physical_execution_authority=false`.

Step 12.3 remains closed.

## Validation

Publication requires:

- Python compile;
- full pytest suite;
- JSON validation;
- Alpha13 release-contract validation;
- Foundation Regression CI.
