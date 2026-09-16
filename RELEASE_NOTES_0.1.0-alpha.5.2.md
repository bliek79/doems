# DOEMS 0.1.0-alpha.5.2 - Status Options Hotfix

## Fix

- Fix `sensor.doems_status` becoming unavailable after Solar P3.0 configuration.
- The status sensor now counts configured options with type-safe comparisons instead of set membership, so list-valued Solar Foundation options such as inverter groups and arrays no longer raise `TypeError: unhashable type: 'list'`.
- Add a regression test covering list-valued Solar options and the Alpha5.2 version contract.

## Scope

This release is intentionally limited to the DOEMS Status regression. Solar P3.0 topology, Energy Forecast, Alpha41 Solar Freeze, storage contracts and safety constraints are unchanged.

P3.1 remains in draft PR #7 and is not included in this release.

## Live validation

After upgrading and restarting Home Assistant:

- `sensor.doems_status` should be available and report `ready`.
- `binary_sensor.doems_solar_foundation_ready` should remain on/ready.
- Existing Solar Foundation IDs and topology signature should remain unchanged.
