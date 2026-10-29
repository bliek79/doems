# DOEMS

DOEMS is a Home Assistant Energy Management System integration built component by component under the technical identity `doems`.

## Current stage

`0.3.0-alpha.5.1` implements **DOEMS 3.0 chapter 5: Plan72**, an observational 72-hour battery-energy planner. Development continues from the functionally validated chapter-4 release `v0.3.0-alpha.4.3`, commit `75516b5aa99282b03b91c1f5b534c02b7b07ce82`. Chapter-4 Energy Need and the existing forecast interfaces remain in place. Publication is gated by automated checks; chapter-5 live validation in Home Assistant is still pending.

The current integration provides:

- native 15-minute Energy Forecast with a rolling 72-hour / 288-slot horizon;
- component-owned Energy Forecast learning history and generic source configuration;
- generic Solar System -> inverter group(s) -> 1..N array configuration;
- Solar P3.1 Open-Meteo runtime with native 15-minute / 72-hour / 288-slot output;
- Prices P4 with Stroomvoorspeller market data, known-price priority, a 76-hour internal buffer and an exact 72-hour / 288-slot public timeline;
- user-configurable tariff profiles with separate import and export components;
- optional gas market/all-in publication with explicit source semantics: either the official EnergyZero market action (`MARKET_WITH_VAT`) or a validated generic Home Assistant EUR/m³ market-price sensor;
- optional `sensor.doems_prices_gas_vs_electricity`, normalizing gas all-in to EUR/kWh with a fixed 9.77 kWh/m³ higher-heating-value basis and exposing the current electricity/gas price ratio;
- the existing approved Dummy OS `brand/icon.png`, reused byte-for-byte from the other working integrations;
- the optional, read-only Energy Need calculation and its eleven existing entities;
- optional Plan72 with one continuous 288-quarter projection, physical energy/power limits, separate safety and trade flows, and 35 registered observation entities;
- no EMS physical execution authority.

## Installation and upgrade

1. Select the intended DOEMS release through HACS or install it manually. For chapter-5 validation, select `v0.3.0-alpha.5.1` explicitly after that pre-release is published.
2. Restart Home Assistant.
3. Open **DOEMS -> Configure / Options**.
4. Enable only the components you want to configure. Plan72 requires **Energy Forecast, Solar Foundation, Prices Forecast and Energy Need**.
5. Existing component settings are prefilled when reconfiguring.
6. Plan72 starts disabled. To use it, enable Plan72 and enter explicit permitted charge and discharge power limits in watts. The planner reuses the Energy Need battery sources, reserve and efficiency; it does not change the battery settings.

See [chapter-5 release notes](RELEASE_NOTES_v0.3.0-alpha.5.1.md) for the validation steps. The optional [Plan72 validation card](examples/plan72_validation_card.yaml) uses standard Home Assistant cards and does not replace any existing dashboard.

## Energy Forecast

Energy Forecast retains the native DOEMS time contract: 15-minute resolution, 72-hour rolling horizon and 288 forecast slots. Its public entities use the `sensor.doems_energy_*` namespace. The richer legacy learning/evidence layers remain outside this clean runtime until they have enough validation evidence to justify promotion.

## Solar Forecast

Solar uses a provider-neutral installation contract with stable inverter-group and array IDs. Open-Meteo is the current primary provider. The P3.1 runtime publishes a generic 1..N array forecast while preserving the fixed 15-minute / 72-hour / 288-slot contract.

The obsolete Alpha41 Solar reference freeze was removed in Alpha7.7. The existing idempotent setup cleanup removes its component-owned legacy storage when present. Local shading/obstruction learning is outside the current Solar forecast implementation.

## Energy Need

Chapter 4 calculates the expected household energy deficit until the next usable solar period, the configured extra reserve, available battery energy and theoretical grid-charge need. Its eleven `doems_ems_*` entities are preserved. The existing usable-solar definition remains eight consecutive quarters with positive solar production covering the household demand in every quarter; otherwise the full 72-hour horizon is used.

The theoretical grid-charge need can exceed battery capacity over a multi-day horizon. Plan72 distributes physically possible charging over time; it does not treat that total as a single charge instruction. Likewise, theoretical tradable energy is not permission to export the battery's full contents.

## Plan72

Plan72 projects household demand, solar production, import/export prices and battery SOC over **72 hours, 288 UTC quarters**. It preserves the original strategy: solar first supplies the home, solar surplus charges the battery, necessary grid charging protects later household supply and reserve, and only a physically feasible beneficial surplus trade is considered.

The planner selects exact timestamps from the existing forecast and price buffers. It retains known-versus-forecast price provenance and the original source resolution. Automatic trade must preserve the solar charging already present in the protected reference route. Each run uses a frozen input snapshot in one executor worker; repeated identical notifications are coalesced and superseded results are discarded.

The current incomplete quarter is outside the forecast window. The latest measured SOC is assumed at the next complete quarter boundary, with its observation time and the unmodelled start interval exposed in timeline source metadata. Flow energies are AC kWh; stored battery energy and reserve are battery-side kWh.

`Plan72 Valid` confirms a valid calculation, not execution permission. `limited` is a valid projection with a visible reserve breach, unresolved physical shortage or limited manual constraint. `Plan72 Reserve Satisfied` reports whether the entire projected route, including its initial SOC and intra-quarter minima, respects the reserve target. The passive self-consumption model still follows the hardware minimum; it does not invent a device command that holds the extra software reserve.

The calculation API supports supplied manual-plan constraints and their priority. The Home Assistant runtime passes an empty manual-plan set until the chapter-7 Plan Store is connected. Chapter 5 does not fill the three execution slots, schedule actions or control the battery.

Trading is a bounded deterministic route comparison, not a claim of a global economic optimum. Its default minimum incremental margin is **0.10 EUR per exported AC kWh**, and trade calculations are enabled by default within Plan72. If no trade is accepted, the best-trade times/prices may remain unknown while the overall energy projection is valid.

The complete input/output contract, all 35 entity IDs and the known limitations are documented in [DOEMS 3.0 chapter 5 Plan72](docs/DOEMS3_CHAPTER5_PLAN72.md).

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

Forecast, Energy Need and Plan72 are data/calculation layers. `physical_execution_authority` remains false. The existing read-only Home Assistant data-action call (`energyzero.get_gas_prices`) is retained; Plan72 adds no battery, inverter or other physical equipment service calls.

## License

DOEMS is released under the MIT License. See [LICENSE](LICENSE).
