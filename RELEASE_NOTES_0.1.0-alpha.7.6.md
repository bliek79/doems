# DOEMS 0.1.0-alpha.7.6 - Exact Existing Brand Icon

Alpha7.6 fixes only the DOEMS branding source.

## Exact fix

- DOEMS now uses the existing approved Dummy OS brand icon byte-for-byte.
- Source references already used by the working integrations:
  - `bliek79/dummy-os-energy/custom_components/dummy_os_data/brand/icon.png`
  - `bliek79/dummy-os-anker-ems/custom_components/anker_ems/brand/icon.png`
- Both existing integrations use the same Git blob:
  `fb0dd2dee9b6c7074da8bdde0f5663260677c779`
- DOEMS keeps only `custom_components/doems/brand/icon.png`.
- The Alpha7.5 generated logo/dark/@2x variants and brand-builder are removed.
- No crop, no generated replacement, no MDI and no new artwork.

## Unchanged

- Energy Forecast unchanged.
- Solar P3.1 unchanged.
- Prices P4 unchanged.
- Gas source semantics unchanged.
- `sensor.doems_prices_gas_vs_electricity` unchanged.
- Native 15 minutes / 72 hours / 288 slots unchanged.
- Prices 76 hours / 304 internal slots unchanged.
- `physical_execution_authority=false`.

## Live check

After HACS upgrade and Home Assistant restart, check only that the general DOEMS integration branding shows the same familiar logo as the other Dummy OS integrations.
