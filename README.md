# DOEMS

DOEMS is a Home Assistant Energy Management System integration built component by component under the technical identity `doems`.

## Current stage

`0.1.0-alpha.7.5` is a focused **single-brand-logo fix**. DOEMS keeps one approved logo; Home Assistant's general integration icon roles now reuse the complete logo instead of a cropped sub-mark. Runtime logic is unchanged.

The current integration provides:

- native 15-minute Energy Forecast with a rolling 72-hour / 288-slot horizon;
- component-owned Energy Forecast learning history and generic source configuration;
- generic Solar System -> inverter group(s) -> 1..N array configuration;
- Solar P3.1 Open-Meteo runtime with native 15-minute / 72-hour / 288-slot output;
- Prices P4 with Stroomvoorspeller market data, known-price priority, a 76-hour internal buffer and an exact 72-hour / 288-slot public timeline;
- user-configurable tariff profiles with separate import and export components;
- optional gas market/all-in publication with explicit source semantics: either the official EnergyZero market action (`MARKET_WITH_VAT`) or a validated generic Home Assistant EUR/m³ market-price sensor;
- optional `sensor.doems_prices_gas_vs_electricity`, normalizing gas all-in to EUR/kWh with a fixed 9.77 kWh/m³ higher-heating-value basis and exposing the current electricity/gas price ratio;
- one approved DOEMS brand logo reused consistently for Home Assistant logo/icon roles;
- no EMS physical execution authority.

## Installation and upgrade

1. Install the latest DOEMS release through HACS or manually.
2. Restart Home Assistant.
3. Open **DOEMS -> Configure / Options**.
4. Enable only the components you want to configure: Energy Forecast, Solar Foundation and/or Prices Forecast.
5. Existing component settings are prefilled when reconfiguring.

## Energy Forecast

Energy Forecast retains the native DOEMS time contract: 15-minute resolution, 72-hour rolling horizon and 288 forecast slots. Its public entities use the `sensor.doems_energy_*` namespace. The richer legacy learning/evidence layers remain outside this clean runtime until they have enough validation evidence to justify promotion.

## Solar Forecast

Solar uses a provider-neutral installation contract with stable inverter-group and array IDs. Open-Meteo is the current primary provider. The P3.1 runtime publishes a generic 1..N array forecast while preserving the fixed 15-minute / 72-hour / 288-slot contract.

The Alpha41 Solar reference freeze remains available for migration validation. Local shading/obstruction learning is a later observer-only Solar expansion and is not part of Alpha7.

## Prices P4

Stroomvoorspeller is the primary electricity market source. Prices normalizes source data into the same native quarter-hour time contract as Energy and Solar.

Source behavior:

- known 15-minute prices are preferred when available;
- known hourly prices remain an explicit fallback/source option;
- forecast hours are expanded to quarter-hour slots while retaining `source_resolution_minutes`;
- known values always win over forecast values for the same timestamp;
- current price never silently substitutes a future forecast value;
- the internal buffer is 76 hours / 304 expected quarter slots;
- the public timeline is an exact 72 hours / 288 positions, with missing timestamps remaining explicitly missing.

Tariff configuration is generic and belongs to the DOEMS Options Flow. Users enter their own profile ID, supplier label, valid-from date, VAT and separate import/export supplier and tax components. Fixed daily supply/grid costs and tax credit remain visible in the tariff profile but are not spread across quarter-hour ranking prices.

Public Prices interface:

- `sensor.doems_prices_status`
- `sensor.doems_prices_market_current`
- `sensor.doems_prices_import_current`
- `sensor.doems_prices_export_current`
- `sensor.doems_prices_timeline`
- `sensor.doems_prices_tariff_profile`
- optional gas market/all-in states when gas publication is enabled
- optional `sensor.doems_prices_gas_vs_electricity` when gas publication is enabled

Each timeline point is provider-neutral and exposes timestamp, market price, import all-in, export all-in, source kind, source resolution and available forecast metadata. `examples/prices_p4_forecast_card.yaml` renders exactly two primary lines: **Import all-in** and **Export all-in**.

Optional gas publication keeps the all-in formula explicit: gas market price including VAT + locally configured supplier component + locally configured tax component. EnergyZero mode calls `energyzero.get_gas_prices` with VAT included so DOEMS receives an explicitly requested market price instead of relying on the semantics of EnergyZero's convenience sensor. Generic sensor mode remains available for third-party providers and validates that the selected sensor uses EUR/m³.

When gas is enabled, `sensor.doems_prices_gas_vs_electricity` exposes the gas all-in price normalized to EUR/kWh using a fixed 9.77 kWh/m³ higher heating value. Its attributes also expose the current electricity import all-in price and the ratio `electricity_import / gas_equivalent`. This is an energy-carrier price comparison only; boiler efficiency and heat-pump COP are intentionally excluded.

## Identity and safety

All public DOEMS object IDs start with `doems_`. Active integration code lives under `custom_components/doems`, domain `doems`, and component-owned storage uses `doems.*` namespaces.

Forecast modules are data/configuration layers. `physical_execution_authority` remains false. Alpha7.5 retains the single read-only Home Assistant data-action call (`energyzero.get_gas_prices`) and no battery, inverter or other physical equipment service calls.

## License

DOEMS is released under the MIT License. See [LICENSE](LICENSE).
