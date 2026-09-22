# DOEMS 0.1.0-alpha.12 - Plan72 Observability Parity Repair

## Scope

Alpha12 repairs a public-observability gap introduced during the standalone DOEMS migration.

No planner, forecast, scheduling, safety, controller or physical-execution behavior is changed. The existing DOEMS Plan72 calculation remains authoritative; this release only restores the public Home Assistant sensor contract needed to display the same Plan72 information that was visible in the working `dummy-os-anker-ems` source.

## Restored public Plan72 observability

The release adds DOEMS-native Plan72 sensors for:

- Plan72 status;
- Plan72 hours, including the full existing `auto_plan_72h_plan` as the `plan` attribute;
- end SOC;
- minimum SOC;
- current dynamic reserve;
- maximum dynamic reserve;
- current execution reserve;
- minimum execution headroom;
- execution-buffer breach hours;
- solar-horizon status;
- incomplete solar-horizon hours;
- solar charge;
- grid safety charge;
- grid trade charge;
- home discharge;
- grid trade discharge.

The Plan72 Hours sensor exposes already-calculated row fields including:

- time;
- import/export price and price source;
- solar and home-consumption energy;
- solar charge;
- safety charge;
- trade charge;
- discharge to home;
- discharge to grid;
- SOC start/end;
- dynamic reserve;
- execution reserve;
- execution headroom;
- action.

## Recorder behavior

The large `plan` attribute is explicitly unrecorded, matching the working source behavior. Home Assistant can use the attribute for live dashboards without writing every complete Plan72 array to Recorder history.

## Physical safety boundary

Alpha12 does not add or enable physical battery control.

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
- Alpha12 release-contract validation;
- Foundation Regression CI.
