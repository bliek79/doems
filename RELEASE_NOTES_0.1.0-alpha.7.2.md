# DOEMS 0.1.0-alpha.7.2 - Prices Entity Registration Hotfix

Alpha7.2 fixes the live Home Assistant issue found after a successful Alpha7.1 Prices configuration: the Prices runtime existed, but its public `sensor.doems_prices_*` outputs were not registered as normal Home Assistant SensorEntity entities.

## Fixed

- Adds registered SensorEntity entities for:
  - `sensor.doems_prices_status`
  - `sensor.doems_prices_market_current`
  - `sensor.doems_prices_import_current`
  - `sensor.doems_prices_export_current`
  - `sensor.doems_prices_timeline`
  - `sensor.doems_prices_tariff_profile`
- Registers optional gas entities when gas prices are enabled:
  - `sensor.doems_prices_gas_market`
  - `sensor.doems_prices_gas_all_in`
- Attaches all Prices entities to the existing DOEMS config entry/device with stable unique IDs and suggested object IDs.
- Moves public state ownership to the Home Assistant entity platform for the active Alpha7.2 runtime, preventing ad-hoc direct states from occupying the canonical entity IDs before registration.
- Keeps status and diagnostics available even when the external market source is degraded or unavailable.

## Unchanged

- Stroomvoorspeller remains the primary electricity market source.
- Known PT15M prices still take priority where available, with explicit hourly fallback according to the configured resolution preference.
- The internal Prices buffer remains 76 hours / 304 quarter-hour slots.
- The public forecast contract remains 72 hours / 288 native 15-minute slots.
- Import and export tariffs remain separate and configurable.
- Fixed daily costs remain excluded from quarter ranking.
- Gas remains optional and uses the user-selected Home Assistant market-price sensor.
- No EMS execution or physical control authority is added.

## Live validation after upgrade

After installing Alpha7.2 and restarting Home Assistant, verify that the registered `sensor.doems_prices_*` entities are visible under DOEMS, that the timeline reports the expected 288-slot contract, that the configured tariff profile is preserved, and that market/import/export values can be compared slot-for-slot with the existing reference integration before Prices is marked fully migrated.
