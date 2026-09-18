# DOEMS 0.1.0-alpha.7.3 - Prices Gas Market Semantics Fix

Alpha7.3 fixes the gas-source semantics issue found during live Alpha7.2 validation. The existing gas all-in arithmetic was correct, but the selected EnergyZero convenience sensor could no longer safely be assumed to represent an explicit market price after the Home Assistant 2026.9 EnergyZero changes.

## Fixed

- Adds an explicit gas source mode to Prices:
  - **EnergyZero market action**: calls `energyzero.get_gas_prices` with `incl_vat: true`, explicitly requesting the EnergyZero market price including VAT.
  - **Home Assistant market-price sensor**: keeps the provider-neutral path for other integrations, with validation that the selected source is a gas price in EUR/m³.
- Adds an EnergyZero config-entry selector for the action route.
- Prevents an electricity-price sensor (EUR/kWh) from being accepted as a generic gas market-price source.
- Publishes traceable gas-source diagnostics: source mode, source entity/config entry, price basis, source status, error, timestamp and response-point count.
- Supports both the current one-point daily EnergyZero gas response and an older repeated-hourly response shape.
- Keeps missing/error values explicit; no source failure is converted to zero.
- Does **not** subtract local tariff components from an upstream sensor as a heuristic.

## Gas price contract

`gas_all_in = gas_market_incl_vat + gas_supplier_incl_vat + gas_tax_incl_vat`

Fixed daily gas supply/grid costs remain tariff-profile metadata and are not spread across market periods.

## Unchanged

- Electricity Prices parity and calculation logic are unchanged.
- Stroomvoorspeller remains the electricity market source.
- Internal price buffer: 76 hours / 304 quarter-hour positions.
- Public electricity timeline: 72 hours / 288 native 15-minute positions.
- Import and export prices remain separate.
- Energy Forecast and Solar P3.1 are unchanged.
- Dashboard contract remains exactly two primary Prices Apex lines: **Import all-in** and **Export all-in**.
- No battery, inverter or other physical control authority is added; `physical_execution_authority=false` remains binding.

## Live validation after upgrade

1. Upgrade to Alpha7.3 and restart Home Assistant.
2. Open **DOEMS -> Configure / Options -> Prices -> Optional gas prices**.
3. Select **EnergyZero market action - explicit market incl. VAT**.
4. Select the active EnergyZero config entry.
5. Keep the existing local gas tariff components.
6. Verify `sensor.doems_prices_gas_market` reports:
   - `source_mode=energyzero_market_action`
   - `source=energyzero.get_gas_prices`
   - `price_basis=market_incl_vat`
   - `source_status=ok`
7. Verify `sensor.doems_prices_gas_all_in = gas_market + configured variable gas components`.

Prices is only fully live green after this runtime check.
