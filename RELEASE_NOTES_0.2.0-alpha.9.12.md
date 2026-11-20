# DOEMS 0.2.0-alpha.9.12

Maintenance release based on v0.2.0-alpha.9.11.

- Add read-only `sensor.doems_solar_forecast_remaining_today` (kWh) to the existing Solar Forecast sensors.
- Derive the remaining energy for the current local calendar day from the rolling 15-minute Open-Meteo solar forecast.
- Keep the original `sensor.doems_solar_forecast_today_total` and other Solar entities unchanged.
- No changes to forecast model, Plan72, scheduler, prices or battery execution.

Install via HACS after publication and reload/restart the DOEMS integration to register the additional entity. The Home Assistant entity ID may receive a suffix if the suggested ID is already reserved.
