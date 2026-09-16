# DOEMS 0.1.0-alpha.4 - Alpha41 Solar Reference Freeze

## Scope

Adds the technical tooling required to freeze the proven Alpha41 Solar runtime as an immutable reference before Solar P3.0 is designed. It does not implement a new DOEMS Solar Forecast and it does not change Alpha41.

## New

- One-time Alpha41 Solar reference-freeze manager with component-owned storage at `doems.solar_reference_freeze`.
- `binary_sensor.doems_alpha41_solar_freeze_captured` for readiness, blockers and persistent snapshot metadata.
- `button.doems_capture_alpha41_solar_freeze` for an explicit one-time capture.
- Stock-card dashboard at `examples/alpha41_solar_freeze_dashboard.yaml`.
- Capture of the complete raw 288-slot Solar timeline plus SHA256, local/UTC capture times, model/status, actual North/South/Total, next quarter and today/tomorrow North/South/Total.
- Restores the intended DOEMS brand variants from the approved light-logo artwork during publication.

## Freeze gate

Capture is blocked unless the live reference has source status `ok`, model `open_meteo_gti_physical_v0.1`, 15-minute resolution, 72-hour horizon, exactly 288 raw points, the exact Alpha41 point format, continuous timestamps and readable actual/forecast values. A failed gate never stores a partial snapshot. After a successful capture the button is unavailable and the normal integration exposes no overwrite/reset action.

## Storage and Sheets

The snapshot is restart-persistent and owned by DOEMS. Raw points are exposed for technical inspection but excluded from Recorder attributes. Google Sheets remains read-only; only the capture timestamp is stored as a pending validation anchor.

## Unchanged

P2.1 Energy Forecast model, native 15 minutes / 72 hours / 288 slots architecture, source signature, learning hierarchy and `doems.energy_forecast` storage contract are unchanged. EMS remains disabled, physical execution authority remains false and no physical Home Assistant service calls are introduced.

## Reference identity

- Alpha41 release: `0.2.0-alpha.41`
- Alpha41 commit: `0dbf9dd68345d9a5dd96d82591aa1d8b93689415`
- Repository: `bliek79/dummy-os-energy`

## Live acceptance

Upgrade to Alpha4, restart Home Assistant, add the supplied dashboard, verify freeze status `ready`, press **Maak Solar Freeze** exactly once, confirm snapshot ID/UTC/local time/288 slots/SHA256, restart Home Assistant and confirm the same snapshot is restored. Only then use the captured timestamp to check the existing Google Sheets Solar validation rows read-only.
