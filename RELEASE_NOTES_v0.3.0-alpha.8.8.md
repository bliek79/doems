# DOEMS v0.3.0-alpha.8.8 - Solar Remaining Today

Maintenance release based strictly on v0.3.0-alpha.8.7 (commit ff5b80a572fecc701807f5d9dab7fc162fd6f5d2).

- Add one read-only Solar Forecast sensor: `sensor.doems_solar_forecast_remaining_today` (kWh).
- Reuse the existing rolling 15-minute Open-Meteo forecast and its `energy_for_local_date(today)` calculation. This is forecast energy remaining until local midnight, not an accumulated production meter.
- Preserve `sensor.doems_solar_forecast_today_total`, the 72-hour/288-slot timeline, northern/southern PV arrays, and all existing Solar entities.
- Do not change any Plan72, Action Bridge, Plan Store, Scheduler, source prices, planner strategy or battery execution behavior.
- Observer-only: physical execution remains disabled as in alpha.8.7.

The two today sensors intentionally use the same rolling forecast calculation and may display the same numerical kWh value. Runtime Home Assistant validation is still required after installation.

This release must be published from a validated, immutable DOEMS 3.0 source commit with `doems.zip`, `RELEASE_PROVENANCE.json` and `SHA256SUMS.txt`.
