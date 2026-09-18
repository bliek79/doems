# DOEMS 0.1.0-alpha.7.4 - Gas vs Electricity Price Sensor

Alpha7.4 adds one read-only Prices sensor for comparing gas and electricity on the same energy-price unit without mixing device efficiency into the Prices layer.

## Added

- New registered Home Assistant entity:
  - `sensor.doems_prices_gas_vs_electricity`
- Sensor state: current gas all-in normalized from EUR/m³ to EUR/kWh.
- Fixed conversion basis: **9.77 kWh/m³**, published as `gas_energy_factor_kwh_m3`.
- Explicit basis label: `gas_energy_basis=higher_heating_value`.
- Comparison attributes:
  - `gas_all_in_eur_m3`
  - `gas_equivalent_eur_kwh`
  - `electricity_import_eur_kwh`
  - `electricity_to_gas_price_ratio`
  - `comparison_scope=energy_carrier_price_only`
  - `efficiency_or_cop_included=false`
- Existing gas provenance from Alpha7.3 remains attached to the new sensor.
- Missing electricity data keeps the ratio null; missing/invalid gas data never becomes zero.

## Calculation contract

`gas_equivalent_eur_kwh = gas_all_in_eur_m3 / 9.77`

`electricity_to_gas_price_ratio = electricity_import_eur_kwh / gas_equivalent_eur_kwh`

The comparison intentionally excludes boiler efficiency, direct-electric efficiency and heat-pump COP. Those belong to later heat/optimization logic, not Prices.

## Unchanged

- Energy Forecast remains native 15 minutes / 72 hours / 288 slots.
- Prices internal buffer remains 76 hours / 304 quarter-hour positions.
- Public Prices timeline remains 72 hours / 288 positions.
- Stroomvoorspeller electricity source logic is unchanged.
- EnergyZero explicit gas market action from Alpha7.3 is unchanged.
- Gas all-in remains market + supplier + tax; fixed daily gas costs remain metadata.
- The Prices Apex contract remains exactly two primary lines: **Import all-in** and **Export all-in**.
- No physical execution authority is added.

## Live validation after upgrade

With gas prices enabled, verify:

1. `sensor.doems_prices_gas_vs_electricity` exists under the DOEMS device.
2. With gas all-in = 1.711679 EUR/m³, the sensor state is approximately **0.175197 EUR/kWh**.
3. `gas_energy_factor_kwh_m3=9.77`.
4. `gas_energy_basis=higher_heating_value`.
5. `electricity_import_eur_kwh` equals the current DOEMS import all-in sensor value.
6. `electricity_to_gas_price_ratio` equals electricity import divided by gas equivalent.
7. `physical_execution_authority=false`.
