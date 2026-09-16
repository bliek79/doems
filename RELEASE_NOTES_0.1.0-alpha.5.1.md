# DOEMS 0.1.0-alpha.5.1 - Solar Options Hotfix

## Why this hotfix exists

During the first live Solar P3.0 configuration on Alpha5, the DOEMS Options Flow stopped after **Battery Power** with Home Assistant's generic `Unknown error occurred` message.

The selected battery power sensors were not the cause. The following Solar System form contained two unitless number fields (`solar_inverter_group_count` and `solar_array_count`) whose selector configuration explicitly serialized `unit_of_measurement=None`. Current Home Assistant selector validation expects a string whenever that key is present.

## Fixed

- Unitless number selectors now omit `unit_of_measurement` completely.
- kW, kWp and degree inputs keep their explicit units.
- Added regression tests for the exact Alpha5 failure mode.
- No Solar P3.0 topology semantics, Energy Forecast behavior, freeze data or storage contracts are changed.

## Approved DOEMS icon / branding

This hotfix also carries forward the previously approved DOEMS branding exactly as agreed. It does not introduce new artwork.

The release contains and validates:

- `custom_components/doems/brand/icon.png`
- `custom_components/doems/brand/icon@2x.png`
- `custom_components/doems/brand/dark_icon.png`
- `custom_components/doems/brand/dark_icon@2x.png`
- `custom_components/doems/brand/logo.png`
- `custom_components/doems/brand/logo@2x.png`
- `custom_components/doems/brand/dark_logo.png`
- `custom_components/doems/brand/dark_logo@2x.png`

Home Assistant integration/device presentation and HACS naming remain **DOEMS**. No active Dummy OS Energy branding is reintroduced.

## Preserved invariants

- Native contract remains 15 minutes / 72 hours / 288 slots.
- Alpha41 Solar reference snapshot remains immutable.
- Solar P3.0 stays installation/topology-only; no DOEMS Solar forecast runtime yet.
- Google Sheets remains read-only.
- `physical_execution_authority=false`; no physical Home Assistant service calls.

## Live validation after upgrade

1. Upgrade to `0.1.0-alpha.5.1` through HACS.
2. Restart Home Assistant.
3. Open DOEMS Options and enable Solar Foundation.
4. Keep existing Energy Forecast / Power Balance selections unchanged.
5. Submit the Battery Power step; the flow must now continue to **Solar System** without error.
6. Complete the Solar Foundation configuration and validate `binary_sensor.doems_solar_foundation_ready` plus restart-stable `topology_signature`.
