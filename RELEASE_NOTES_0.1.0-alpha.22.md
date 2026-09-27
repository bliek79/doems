# DOEMS 0.1.0-alpha.22 - Solar Quarter-Roll Publication Fix

## Purpose

Alpha22 fixes the public Solar forecast cadence discovered by the new DOEMS
validation logging. The Open-Meteo source refresh itself was healthy, but the
Home Assistant Solar entities were only republished when the hourly provider
refresh notified listeners.

As a result, between provider refreshes the stored Home Assistant state could
still show the previous quarter as `forecast_start` / next quarter, and
`age_minutes` could remain frozen at the age from the last publication.

## Fix

The Solar runtime now adds a lightweight native quarter publication tick at
minute 00/15/30/45, at second 30.

That tick:

- only calls the existing listener notification path;
- performs no Open-Meteo request;
- performs no forecast recalculation;
- performs no Home Assistant control service call;
- preserves the existing hourly provider refresh at :00:20.

This makes the already-existing rolling source buffer visible in Home Assistant
on the native 15-minute cadence.

## Expected public behavior

On every natural quarter boundary:

- `sensor.doems_solar_forecast_timeline` rolls to the first still-future
  15-minute slot;
- `sensor.doems_solar_forecast_next_quarter` starts at that same slot;
- the public timeline remains 288 slots while the source buffer is sufficient;
- `sensor.doems_solar_source_status.age_minutes` is republished and advances;
- stale / expired status is reevaluated from current age and remaining points.

## Architecture unchanged

- Native Solar contract remains 15 minutes / 72 hours / 288 slots.
- Open-Meteo fetch cadence remains hourly.
- The four-slot rolling source buffer remains unchanged.
- Array identity/order, topology and model math remain unchanged.
- Energy, Prices and EMS planner policy are unchanged.
- The separate alpha21 `shadow` naming cleanup is not part of this release.
- `physical_execution_authority=false` remains unchanged.

## Validation

Regression coverage verifies that the quarter tick is registered on
00/15/30/45, republishes through `_notify()`, and cannot call
`async_refresh()`. The existing hourly provider refresh remains intact.

Live acceptance after installation is read-only through the existing
`DOEMS Solar Forecast` Google Sheet: two consecutive quarter writes must show
a correctly advanced forecast start / target start and a progressing source
age without additional provider fetches.
