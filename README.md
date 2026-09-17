# DOEMS

DOEMS is a clean Home Assistant Energy Management System integration built component by component under the technical identity `doems`.

## Current stage

`0.1.0-alpha.7` adds the **Prices P4.1 Runtime** on top of the live Energy Forecast and Solar P3.1 runtime.

The current integration provides:

- native 15-minute Energy Forecast with a 72-hour / 288-slot horizon;
- Direct Home Power and Power Balance source routes;
- immutable Alpha41 Solar reference-freeze tooling;
- generic Solar System → inverter group(s) → 1..N array configuration;
- native Open-Meteo Solar P3.1 forecast with the same 15-minute / 72-hour / 288-slot contract;
- Prices P4.1 with Stroomvoorspeller market data, known-over-forecast priority, 76-hour buffer and 288-position public timeline;
- independent configurable import and export tariff components;
- optional gas current/all-in companion pricing from a user-selected market-price sensor;
- approved local DOEMS icon/logo assets;
- no EMS decision/execution chain and no physical battery control.

## Installation and upgrade

1. Install `0.1.0-alpha.7` through HACS or manually.
2. Restart Home Assistant.
3. Open **DOEMS → Configure / Options**.
4. Keep existing Energy/Solar selections unchanged unless intentionally reconfiguring them.
5. Enable **Prices Forecast** and configure your own tariff profile.
6. Add `examples/prices_p4_1_forecast_card.yaml` for the two-line Import/Export validation graph.

## Prices P4.1

Stroomvoorspeller is the first Prices provider adapter. Provider details stay at the adapter boundary: DOEMS normalizes market data to EUR/kWh and exposes one stable quarter-hour contract.

The Prices contract uses:

- `auto`, `15_min` or `60_min` preference for known price resolution;
- known prices before forecast values for identical timestamps;
- PT15M known data when available in `auto`, with explicit hourly known fallback;
- hourly forecast provenance repeated into quarter-hour slots while retaining `source_resolution_minutes=60`;
- an internal **76-hour / 304-slot** timestamp-indexed buffer;
- a public rolling **72-hour / 288-position** timeline;
- explicit null/missing records instead of shifting later values forward;
- independent import and export marginal all-in prices;
- tariff profile metadata including stable profile ID, supplier label, effective date, VAT and fixed daily costs.

Daily fixed costs remain tariff-profile metadata and are not divided over quarter-hour prices. This keeps slot ranking clean for future planner use.

Public Prices entities:

- `sensor.doems_prices_status`
- `sensor.doems_prices_market_current`
- `sensor.doems_prices_import_current`
- `sensor.doems_prices_export_current`
- `sensor.doems_prices_timeline`
- `sensor.doems_prices_tariff_profile`
- optional `sensor.doems_prices_gas_market`
- optional `sensor.doems_prices_gas_all_in`

The current-price entities only use known data for the actual current quarter. A future forecast point is never presented as current actual pricing.

## Prices dashboard contract

The main Prices Apex uses exactly two primary series from `sensor.doems_prices_timeline`:

- **Import all-in**
- **Export all-in**

Market price remains available for diagnostics but is not a third primary graph line.

## Solar P3.1

Solar uses the generic P3.0 installation contract and Open-Meteo GTI per array. It supports 1..N inverter groups and 1..N arrays, stable IDs, AC limits per inverter group and a native 288-slot Solar timeline. Local Shading / Obstruction Learning remains a separate future observer-only phase.

## Alpha41 Solar reference freeze

The previous Alpha41 Solar reference remains immutable under `doems.solar_reference_freeze`, captured as `A41-SOLAR-20260916T105003Z` for read-only migration comparison.

## Identity and safety

All public DOEMS object IDs start with `doems_`. The active package is `custom_components/doems`, domain `doems`, and component-owned storage uses `doems.*` keys.

Home Assistant integration/device presentation and HACS naming remain **DOEMS**. The approved existing DOEMS artwork is retained.

Forecast and Prices modules are observation/configuration only. EMS remains disabled, `physical_execution_authority=false`, and no Home Assistant service calls to physical equipment are introduced.

## License

DOEMS is released under the MIT License. See [LICENSE](LICENSE).
