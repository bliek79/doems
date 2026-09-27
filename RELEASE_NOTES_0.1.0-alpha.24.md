# DOEMS 0.1.0-alpha.24 - Solar Actual Quarter Validation

## Purpose

Alpha24 completes the existing Solar forecast-validation chain by adding a native
DOEMS measurement for the last completed Solar quarter.

The fix does not change the Open-Meteo forecast model, planner policy, safety
chain, execution authority or the native 15-minute / 72-hour / 288-slot
architecture.

## New public sensor

`sensor.doems_solar_actual_quarter`

The sensor integrates the configured total actual Solar power over one complete
native 15-minute quarter and publishes:

- actual quarter energy in kWh;
- period start and end;
- measurement coverage;
- measurement-valid flag;
- actual source entity;
- the forecast value locked for that same quarter at quarter start;
- forecast capture timestamp;
- forecast-minus-actual error in kWh;
- absolute error in kWh;
- percentage error when actual generation is greater than zero.

A restart-partial quarter may still produce an actual measurement when coverage
is sufficient, but it is not compared against a forecast unless the forecast was
locked at the natural quarter boundary.

## Forecast integrity

The Solar forecast manager now exposes an exact cached slot lookup by slot start.
The actual-quarter runtime uses that cached value only; it performs no additional
Open-Meteo request and never recomputes a forecast in hindsight.

At each natural 00/15/30/45 boundary the next quarter forecast is locked before
the quarter is measured. This preserves a fair forecast-versus-actual comparison.

## Google Sheets validation

The existing `DOEMS Solar Forecast` tab remains the only Solar validation tab
and is extended with:

- Actual quarter start
- Actual quarter end
- Actual quarter kWh
- Actual quarter coverage
- Actual quarter valid
- Forecast quarter kWh
- Forecast error kWh
- Forecast absolute error kWh
- Forecast error procent

The existing 103 columns remain unchanged.

## Safety and architecture

Unchanged:

- Solar forecast remains Open-Meteo GTI physical model v0.1;
- provider refresh remains hourly;
- quarter-roll publication remains every native quarter;
- Solar timeline remains exactly 288 slots / 72 hours / 15 minutes;
- no planner or Plan72 policy change;
- no battery-control service call;
- `physical_execution_authority=false`.

## Live acceptance after installation

After the first full natural quarter following restart:

1. verify `sensor.doems_solar_actual_quarter` has period start/end and valid coverage;
2. verify the forecast quarter start matches the measured actual quarter;
3. verify forecast kWh is start-locked, not recomputed after the quarter;
4. verify the nine added Solar Sheet fields are written;
5. verify the existing 103 Solar fields and 288/288 timeline remain green.
