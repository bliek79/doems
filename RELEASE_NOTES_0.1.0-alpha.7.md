# DOEMS 0.1.0-alpha.7 - Prices P4.1 Runtime

## Prices P4.1

This release adds the complete first DOEMS Prices runtime while preserving the native DOEMS forecast contract: **15 minutes / 72 hours / 288 slots**.

- Stroomvoorspeller is the first provider adapter for electricity market prices.
- Known prices always outrank forecast prices for the same timestamp.
- `auto` uses PT15M known prices when available and falls back to known hourly prices for gaps.
- `15_min` uses PT15M known prices without silently replacing missing known quarters with hourly known data.
- `60_min` uses known hourly prices, normalized to quarter-hour slots.
- Hourly forecast values remain hourly provenance but are exposed through four 15-minute slots with `source_resolution_minutes=60`.
- Provider-specific data is normalized to EUR/kWh and published through one provider-neutral timeline.

## Third-party-ready tariff configuration

Prices is configured from DOEMS Options; no ANWB, EnergyZero or installation-specific entity ID is required.

The contract includes:

- stable user-defined tariff profile ID and supplier label;
- effective date and configurable VAT;
- independent import supplier/tax components;
- independent export supplier/tax components, including signed values;
- electricity fixed supply, grid cost and tax-credit values per day;
- optional gas current/all-in pricing from a user-selected Home Assistant gas-market sensor.

Daily fixed costs are stored in the tariff profile but are **not** spread across the 96 quarter-hour prices. The marginal import/export lines therefore retain the correct economic ranking for planner use.

## Public DOEMS Prices contract

New public entities:

- `sensor.doems_prices_status`
- `sensor.doems_prices_market_current`
- `sensor.doems_prices_import_current`
- `sensor.doems_prices_export_current`
- `sensor.doems_prices_timeline`
- `sensor.doems_prices_tariff_profile`
- optional `sensor.doems_prices_gas_market`
- optional `sensor.doems_prices_gas_all_in`

`sensor.doems_prices_timeline` publishes 288 positional records for the rolling 72-hour horizon. Missing data is represented explicitly with `valid=false` and null price fields; later slots never shift forward to conceal a gap.

Current price entities use **known data for the actual current quarter only**. A future forecast point is never silently presented as the current actual price.

## Buffer and diagnostics

- Internal Prices buffer: **76 hours / 304 expected quarter slots**.
- Public timeline: **72 hours / 288 positional quarter slots**.
- Diagnostics retain provider freshness, generated timestamps, source kind, source resolution, PT15M availability, missing slots and duplicates.
- On a temporary provider refresh error the last valid normalized dataset is retained, while status becomes stale/error instead of presenting it as new data.

## Dashboard contract

`examples/prices_p4_1_forecast_card.yaml` contains exactly two primary Apex lines:

1. **Import all-in**
2. **Export all-in**

The raw market price remains available for diagnostics/current-price use but is deliberately not a third primary dashboard line.

## Regression and safety

- Energy Forecast and Solar P3.1 remain unchanged in scope.
- Existing Solar Foundation, Alpha41 freeze and approved DOEMS branding are retained.
- `physical_execution_authority=false` remains binding.
- Prices performs observation/normalization only and makes no physical Home Assistant service calls.
- Google Sheets is not written by this release.

## Live validation gate

After upgrading to Alpha7 and restarting Home Assistant:

1. Open DOEMS Options, enable Prices and enter the tariff profile.
2. Confirm `sensor.doems_prices_status` becomes `ok` or clearly reports partial/stale diagnostics.
3. Confirm `sensor.doems_prices_timeline` reports 288 positional points and 15-minute / 72-hour semantics.
4. Confirm the actual current market/import/export entities use a known current-quarter price only.
5. Confirm import and export all-in values reflect the independently configured tariff components.
6. Add the Prices Apex and confirm exactly the two intended lines: Import all-in and Export all-in.
7. Restart Home Assistant and confirm the configured tariff profile and runtime recover cleanly.
8. Compare accumulated Prices Forecast Evaluation data in Google Sheets read-only; do not add manual validation rows.
