# DOEMS 0.1.0-alpha.5 - Solar P3.0 Foundation

## Scope

This release implements only the documented Solar P3.0 installation/topology foundation. It does **not** yet port the Open-Meteo Solar forecast runtime and it does not enable EMS or physical control.

## Added

- Solar Foundation toggle in DOEMS Options Flow.
- Home Assistant location by default, with explicit latitude/longitude override.
- Generic Solar System → 1..N inverter groups → 1..N arrays model.
- Stable generated `group_id` and `array_id` values, independent from user-facing labels.
- Provider-neutral array geometry: DC kWp, tilt, azimuth (`0=N, 90=E, 180=S, 270=W`).
- Optional inverter-group AC limits.
- Optional total actual Solar power source and optional per-array actual sources.
- Structural validation for topology, geometry and duplicate actual mappings.
- Restart-persistent normalized storage under `doems.solar_foundation`.
- `binary_sensor.doems_solar_foundation_ready` with compact diagnostics and a semantic `topology_signature`.
- Example compact Solar Foundation dashboard card.

## Preserved invariants

- Native future Solar time contract remains 15 minutes / 72 hours / 288 slots.
- Open-Meteo remains the primary provider for the next Solar runtime phase; no Solcast provider is introduced here.
- The Alpha41 reference snapshot remains immutable and is not overwritten.
- Energy Forecast behavior and `doems.energy_forecast` history are unchanged.
- No corrected/shading forecast is introduced.
- `physical_execution_authority=false`; no physical Home Assistant service calls.
- Google Sheets remains read-only.

## Next gate

After live configuration/validation of the Solar Foundation and restart-stable topology signature, P3.1 may port the Alpha41 Open-Meteo physical Solar forecast onto the generic 1..N topology.
