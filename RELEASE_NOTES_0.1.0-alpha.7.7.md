# DOEMS 0.1.0-alpha.7.7 - Alpha41 Solar Freeze Cleanup

## Scope

Alpha7.7 removes the completed Alpha41 Solar reference-freeze tooling from the active DOEMS integration. This is a cleanup release only; it does not redesign Energy, Solar, Prices, planner/EMS logic, or physical execution.

## Removed

- Alpha41 Solar freeze capture button.
- Alpha41 Solar freeze captured binary sensor.
- Solar reference-freeze model and runtime manager.
- Freeze-specific constants and the Home Assistant button platform.
- Freeze example dashboard and freeze contract test.
- Active runtime dependency on the old Alpha41 Solar reference entities.

## Upgrade cleanup

On setup, DOEMS performs an idempotent removal of the retired `doems.solar_reference_freeze` storage record so installations upgrading from the freeze-enabled releases do not retain component-owned orphan storage.

## Preserved contracts

- Native forecast architecture remains 15 minutes / 72 hours / 288 slots.
- Solar Foundation and Solar P3.1 Open-Meteo runtime remain unchanged.
- Energy Forecast remains unchanged.
- Prices P4, including gas and gas-versus-electricity, remains unchanged.
- Existing DOEMS brand icon remains unchanged.
- `physical_execution_authority=false`; no physical control surface is introduced.
- README is intentionally unchanged in this release and will be handled separately.

## Validation

- Python compile and full pytest suite.
- JSON validation.
- Existing Energy, Solar, Prices, branding and Foundation regression contracts.
- Release package verification.
- Freeze files/entities/platform are absent from the active integration.
