# DOEMS

DOEMS is a clean Home Assistant Energy Management System integration built component by component under the technical identity `doems`.

## Current stage

`0.1.0-alpha.4` adds the **Alpha41 Solar Reference Freeze** gate on top of the live-green P2.1 Energy Forecast. P2.1 remains unchanged. Alpha4 does not implement a new DOEMS Solar Forecast; it only captures the proven Alpha41 Solar runtime as an immutable technical reference before Solar P3.0 is designed.

The current integration provides:

- native 15-minute Energy Forecast with a 72-hour / 288-slot horizon;
- component-owned `doems.energy_forecast` learning history;
- Direct Home Power and Power Balance source routes;
- one-time persistent Alpha41 Solar reference-freeze tooling;
- no new DOEMS Solar Forecast yet;
- no Prices layer yet;
- no EMS decision/execution chain and no physical battery control.

## Installation and upgrade

1. Install `0.1.0-alpha.4` through HACS or manually.
2. Restart Home Assistant.
3. Existing Alpha1-Alpha3 config entries and Energy Forecast history are retained.
4. For the Solar freeze, add `examples/alpha41_solar_freeze_dashboard.yaml` as a dashboard/view.
5. Verify freeze status is `ready`, then press **Maak Solar Freeze** exactly once.

## Alpha41 Solar reference freeze

The gate reads only the existing Alpha41 public Solar entities. It validates source status, model identity, 15-minute resolution, 72-hour horizon, exactly 288 raw timeline points, the exact point format, continuous timestamps and the required actual/forecast values.

Public DOEMS entities:

- `binary_sensor.doems_alpha41_solar_freeze_captured`
- `button.doems_capture_alpha41_solar_freeze`

A successful press stores exactly one snapshot under `doems.solar_reference_freeze`. The snapshot contains Alpha41 release/commit identity, local and UTC capture timestamps, model/status, actual North/South/Total, next quarter, today/tomorrow North/South/Total, the complete raw 288-slot timeline and a SHA256 of that timeline. The button then becomes unavailable; no overwrite/reset action is exposed.

Google Sheets remains read-only. The capture timestamp is stored only as a pending time anchor for checking the already accumulated Solar validation rows.

Reference identity:

- release `0.2.0-alpha.41`
- commit `0dbf9dd68345d9a5dd96d82591aa1d8b93689415`
- repository `bliek79/dummy-os-energy`

The reference is formally frozen only after the snapshot survives a Home Assistant restart and the matching Google Sheets validation rows are checked read-only.

## Energy Forecast source modes

### Direct Home Power

Use a reliable current household-load sensor in W or kW.

### Power Balance

DOEMS can reconstruct Home Power from grid, total solar and optional battery charge/discharge power using:

`home = solar + grid_import + battery_discharge - grid_export - battery_charge`

Energy Forecast keeps Normal and Away history separate and uses the proven historical-baseline hierarchy with 28-day recency weighting.

## Identity and safety

All public DOEMS object IDs start with `doems_`. The active package is `custom_components/doems`, domain `doems`, and component-owned storage uses `doems.*` keys.

Energy Forecast and Solar reference-freeze tooling are observer-only. EMS remains disabled, physical execution authority is false, and no Home Assistant service calls to physical equipment are introduced.

## Brand images

Home Assistant local light/dark DOEMS assets live under `custom_components/doems/brand/`. Alpha4 restores the intended existing DOEMS artwork for this content release rather than introducing a new logo design.

## License

DOEMS is released under the MIT License. See [LICENSE](LICENSE).
