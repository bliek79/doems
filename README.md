# DOEMS

DOEMS is a clean Home Assistant Energy Management System integration built component by component under the technical identity `doems`.

## Current stage

`0.1.0-alpha.5` adds the **Solar P3.0 Foundation** after the Alpha41 Solar reference was successfully frozen and restart-validated. P3.0 defines the generic installation and topology contract needed before the native DOEMS Solar Forecast is ported in P3.1.

The current integration provides:

- native 15-minute Energy Forecast with a 72-hour / 288-slot horizon;
- component-owned `doems.energy_forecast` learning history;
- Direct Home Power and Power Balance source routes;
- immutable Alpha41 Solar reference-freeze tooling;
- generic Solar System → inverter group(s) → 1..N array configuration;
- component-owned `doems.solar_foundation` topology storage;
- no new DOEMS Solar Forecast runtime yet;
- no Prices layer yet;
- no EMS decision/execution chain and no physical battery control.

## Installation and upgrade

1. Install `0.1.0-alpha.5` through HACS or manually.
2. Restart Home Assistant.
3. Existing Energy Forecast history and the immutable Alpha41 Solar freeze snapshot are retained.
4. Open **DOEMS → Configure / Options** and enable **Solar Foundation**.
5. Configure the location source, inverter group(s), PV array(s) and optional actual-power sources.
6. Add `examples/solar_p3_0_foundation_card.yaml` to a dashboard for compact validation.

## Solar P3.0 Foundation

P3.0 is deliberately an installation/topology layer, not a new forecast model. Open-Meteo is fixed as the primary provider for the next Solar phase, but P3.0 itself makes no provider requests.

The contract uses:

- Home Assistant latitude/longitude by default, with an explicit override option;
- 1..N inverter groups with stable internal `group_id` values and optional AC limits;
- 1..N PV arrays with stable internal `array_id` values;
- per-array DC kWp, tilt and provider-neutral azimuth;
- canonical azimuth `0=N, 90=E, 180=S, 270=W`, clockwise from true north;
- optional total actual solar power and optional per-array actual power sensors;
- total Solar as aggregation of the configured arrays, never as a competing second model.

Labels can be changed without changing the internal topology signature. A geometry, group-link, stable-ID or actual-source change does change the signature.

Public diagnostic entity:

- `binary_sensor.doems_solar_foundation_ready`

Its attributes expose the normalized install contract, blockers, counts, total DC kWp, known AC limit, actual-source coverage and `topology_signature`. The normalized snapshot is persisted under `doems.solar_foundation`.

P3.0 keeps the future Solar runtime contract fixed at native 15 minutes / 72 hours / 288 slots, but does not publish a DOEMS Solar forecast timeline yet.

## Alpha41 Solar reference freeze

The previous Alpha41 reference remains immutable under `doems.solar_reference_freeze`. It was captured as `A41-SOLAR-20260916T105003Z`, survived a Home Assistant restart with the same snapshot identity/SHA and was linked read-only to the existing Solar validation rows in Google Sheets.

Reference identity:

- release `0.2.0-alpha.41`
- commit `0dbf9dd68345d9a5dd96d82591aa1d8b93689415`
- repository `bliek79/dummy-os-energy`

## Identity and safety

All public DOEMS object IDs start with `doems_`. The active package is `custom_components/doems`, domain `doems`, and component-owned storage uses `doems.*` keys.

Energy Forecast, Solar Foundation and Solar reference-freeze tooling are observer/configuration-only. EMS remains disabled, physical execution authority is false, and no Home Assistant service calls to physical equipment are introduced.

## License

DOEMS is released under the MIT License. See [LICENSE](LICENSE).
