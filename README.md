# DOEMS

DOEMS is a clean Home Assistant Energy Management System integration built component by component under the technical identity `doems`.

## Current stage

`0.1.0-alpha.3` is **P2.1 - Energy Forecast (live-green maintenance)**.

This maintenance build keeps the proven Energy Forecast model and storage contract unchanged, adds local DOEMS brand images, and refreshes the Energy History Status diagnostic immediately when the configured Home Power source becomes available after startup.

The Energy Forecast component provides:

- native 15-minute Energy Forecast;
- 72-hour horizon / 288 forecast slots;
- clean `doems.*` component-owned history storage;
- Normal and Away learning profiles;
- two generic Home Power input routes;
- no Solar Forecast yet;
- no Prices yet;
- no EMS decision/execution chain yet;
- no physical battery control.

## Installation and upgrade

1. Install `0.1.0-alpha.3` through HACS or manually.
2. Restart Home Assistant.
3. Add **DOEMS** if it is a new installation. Existing Alpha1/Alpha2 installations keep their clean config entry and component-owned Energy Forecast history.
4. Open **Settings > Devices & services > DOEMS > Configure**.
5. Enable **Energy Forecast** and complete only the fields required by the chosen Home Power source mode.

### Direct Home Power

Use this route when Home Assistant already has a reliable sensor that represents actual current home load. The selected sensor must use W or kW and should normally be non-negative.

### Power Balance

Use this route when Home Power must be reconstructed from local power flows. Configure grid power, grid sign convention, total current solar power, and optionally positive battery charge/discharge power.

DOEMS normalizes the balance to:

`home = solar + grid_import + battery_discharge - grid_export - battery_charge`

No location, PV geometry, electricity price, SOC, battery capacity or EMS settings are requested in this component step.

## Public entities

Every public DOEMS object ID starts with `doems_`. This naming contract allows installations to exclude DOEMS entities from Home Assistant Recorder with `*.doems_*` entity globs while DOEMS keeps only the component-owned history it needs for learning.

## Energy Forecast behaviour

The model uses a history hierarchy of weekday+quarter, day-type+quarter, quarter-of-day and finally profile mean, with 28-day recency half-life weighting. Normal and Away history are kept separate. A profile with no own valid history does not silently borrow another profile.

Changing the configured source semantics changes the source signature. Incompatible stored learning history is then reset instead of being mixed into the new source contract.

## Alpha3 maintenance fix

During the Alpha2 restart test, component-owned history and the 288-slot forecast were immediately restored correctly, but **Energy History Status** could temporarily remain `source_unavailable` after the physical source sensors had already recovered. Alpha3 adds a temporary one-shot source-recovery listener during setup so quarter-driven diagnostics refresh as soon as the complete canonical Home Power source is available again instead of waiting for the next quarter boundary.

This fix does not change the Energy Forecast model, source signature, storage schema, learning records or physical-control surface.

## Brand images

For Home Assistant 2026.3 and newer, DOEMS ships local light/dark integration icons and logos in `custom_components/doems/brand/`. Home Assistant gives local custom-integration brand images priority over the external brands repository.

## Identity and safety contract

The active integration uses only the new technical identity: package `custom_components/doems`, domain `doems`, storage prefix `doems.*`, and public object-id prefix `doems_`.

P2.1 is observer-only. `ems_enabled` remains false and physical execution authority remains false. No Home Assistant service calls to physical equipment are present.

## License

DOEMS is released under the MIT License. See [LICENSE](LICENSE).
