# DOEMS 0.2.0-alpha.1 - Forecast Reset Baseline

## Purpose

This release starts the clean DOEMS 0.2.0 reset line from the proven DOEMS 0.1.0-alpha.7.7 forecast-only baseline.

The code base is intentionally reset to the state before the EMS/planner build that started with 0.1.0-alpha.7.8. No EMS planning, Plan Store, Scheduler, Safety, execution or physical battery-control code from later 0.1.0 releases is included.

## Baseline

Source baseline:
- DOEMS tag `0.1.0-alpha.7.7`
- source commit `eb01911a40e01c5f01264e2a4d5e297a8ea3870d`

Preserved forecast functionality:
- Energy Forecast
- Solar Forecast / Solar P3.1 Open-Meteo runtime
- Prices P4, including gas pricing
- native 15-minute / 72-hour / 288-slot architecture
- existing DOEMS identity, configuration and forecast-owned storage

## Reset boundary

The following later 0.1.0 EMS/planner layers are deliberately absent:
- EMS configuration introduced from alpha7.8 onward
- copied Alpha76 planner chain
- Plan Store
- manual/automatic Scheduler
- Safety / Prestart / Execution
- physical battery authority

These functions will be reintroduced only through the new reset route, beginning with manual planning and manual SOC replanning before automatic planning.

## Versioning

Only the release/version identity is changed from the alpha7.7 source:
- manifest version: `0.2.0-alpha.1`
- runtime version: `0.2.0-alpha.1`

No forecast decision logic is changed for this release.

## Validation

- Python compile
- full alpha7.7 pytest suite
- JSON validation
- Energy, Solar, Prices and Foundation regression contracts
- release archive verification
