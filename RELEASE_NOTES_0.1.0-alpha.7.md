# DOEMS 0.1.0-alpha.7 - Prices P4 Runtime

This release ports the proven Prices chain into DOEMS as the next forecast module.

## Prices P4
- Stroomvoorspeller remains the primary electricity market source.
- Known 15-minute prices are preferred when available, with explicit hourly known fallback in Auto mode.
- Users can select Auto, 15-minute-known or hourly-known behavior.
- Forecast hours are normalized onto the native DOEMS 15-minute grid while retaining source resolution/provenance.
- Known prices always beat forecast values for the same timestamp.
- Current price never silently uses a forecast value when no known current price exists.
- Internal price buffer remains 76 hours / 304 expected quarter slots.
- Public forecast horizon is 72 hours / 288 exact quarter positions; missing timestamps stay missing and never shift later prices.

## Generic tariff install contract
- Tariff profile ID, supplier label, valid-from date and VAT are user-configurable.
- Import supplier/tax and export supplier/tax are separate user inputs.
- Fixed supply, grid costs and tax credit are retained in the tariff profile but are not smeared across quarter-hour ranking prices.
- Optional gas publication uses a user-selected Home Assistant gas market sensor; no fixed supplier/entity is hard-coded.

## Public interface
- `sensor.doems_prices_status`
- `sensor.doems_prices_market_current`
- `sensor.doems_prices_import_current`
- `sensor.doems_prices_export_current`
- `sensor.doems_prices_timeline`
- `sensor.doems_prices_tariff_profile`
- optional gas market/all-in states when configured

The timeline exposes provider-neutral dictionaries containing time, market price, import all-in, export all-in, known/forecast kind and source resolution. The example Prices Apex deliberately contains exactly two primary lines: Import all-in and Export all-in.

## Safety
Prices remains data/forecast-only. `physical_execution_authority` remains false. No battery, inverter or tariff service is called.
