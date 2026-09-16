# DOEMS 0.1.0-alpha.6 - Solar P3.1 Open-Meteo Runtime

## Solar P3.1

This release activates the first native DOEMS Solar Forecast runtime on top of the live-validated Solar P3.0 Foundation.

- Uses the normalized P3.0 Solar Foundation as the single installation contract for location, inverter groups, PV arrays, geometry and AC limits.
- Uses Home Assistant latitude/longitude when `solar_location_source=home_assistant`; no hardcoded installation location is used by the P3.1 provider runtime.
- Fetches Open-Meteo `global_tilted_irradiance` independently for every configured PV array.
- Preserves the native DOEMS time contract: **15 minutes / 72 hours / 288 forecast slots**.
- Preserves Alpha41 timestamp semantics: Open-Meteo radiation timestamps are treated as backward averages and shifted to the corresponding slot start.
- Keeps the last valid Solar timeline when a temporary provider refresh fails, while exposing freshness/error status explicitly.

## Generic 1..N topology

- Solar forecasting is no longer hardcoded to North/South.
- Every array is identified by its stable `array_id` and linked to a stable inverter `group_id`.
- Canonical DOEMS azimuth remains `0=N, 90=E, 180=S, 270=W` and is translated at the provider boundary to Open-Meteo's convention.
- Forecast power is calculated per array from GTI, DC kWp and the initial physical performance factor `0.90`.
- AC limits are enforced on the **sum of each inverter group**. If a group clips, its member arrays are scaled proportionally rather than being capped independently.
- Missing array data blocks construction of that aligned slot/timeline; missing forecast data is not silently converted to zero.

## Public Home Assistant entities

New P3.1 entities:

- `sensor.doems_solar_source_status`
- `sensor.doems_solar_forecast_timeline`
- `sensor.doems_solar_forecast_next_quarter`
- `sensor.doems_solar_forecast_today_total`
- `sensor.doems_solar_forecast_tomorrow_total`
- `sensor.doems_solar_forecast_model`

The timeline uses the generic point format:

`[unix_ms, total_kwh, total_kw, array_kwh[], array_kw[], array_gti_wm2[]]`

The array-value order is explicitly defined by the `array_ids` attribute.

## Diagnostics and dashboard

- `binary_sensor.doems_solar_foundation_ready` now reports the live `forecast_runtime_active` flag instead of a hardcoded value.
- Solar Source Status exposes provider freshness, last attempt, last successful update, last error, source point counts, Foundation location and topology signature.
- `examples/solar_p3_1_forecast_card.yaml` provides the first compact P3.1 validation dashboard using only public DOEMS entities.

## Regression and safety

- Alpha5.2's `sensor.doems_status` list-option hotfix is retained.
- Existing Energy Forecast, Solar P3.0 Foundation and immutable Alpha41 Solar Freeze contracts remain in place.
- `physical_execution_authority=false` remains binding. P3.1 performs forecast/observation only and does not call physical battery, inverter or EMS services.
- Google Sheets is not written by this release; existing validation data remains read-only.
- The separate DOEMS branding/icon acceptance issue is **not** changed or closed by Alpha6.

## Live validation gate

After upgrading to Alpha6 and restarting Home Assistant, validate before declaring P3.1 live-green:

1. `sensor.doems_solar_source_status` = `ok`.
2. `sensor.doems_solar_forecast_timeline` has exactly 288 points with 15-minute resolution and 72-hour horizon.
3. `binary_sensor.doems_solar_foundation_ready` remains `on/ready`, with the same P3.0 topology signature.
4. Next quarter, today total and tomorrow total populate.
5. Compare the P3.1 outputs side-by-side with the immutable Alpha41 reference for next quarter, today, tomorrow and the full 288-slot timeline.
6. Re-test restart persistence plus stale/expired/provider-failure behavior.
7. Only after the live runtime is stable, inspect accumulated Google Sheets validation data read-only.
