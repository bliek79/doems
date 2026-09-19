# DOEMS 0.1.0-alpha.7.11 - G6 Step 4A EMS Backend Validation

## Scope

Alpha7.11 publishes G6 Step 4A only. It adds explicit backend validation for each of the thirteen existing EMS configuration fields. The UI selectors remain unchanged; invalid submissions are rejected on the EMS form before anything from that submission is stored.

## Individual validation

Numeric fields now enforce type, minimum, maximum and the agreed step/granularity:

- battery_capacity_kwh: 1.0-30.0 kWh, step 0.1
- technical_min_soc_percent: 0-30%, integer
- max_soc_percent: 50-100%, integer
- max_charge_power_w: 100-3500 W, step 100 W
- max_discharge_power_w: 100-3500 W, step 100 W
- software_reserve_percent: 0-30%, step 1
- charge_efficiency_percent: 50-100%, step 1
- discharge_efficiency_percent: 50-100%, step 1
- minimum_trade_margin_eur_per_kwh: EUR 0.00-1.00/kWh, step EUR 0.01/kWh
- startup_delay_seconds: 30-300 s, step 5 s
- away_schedule_enabled: boolean only
- away_start: empty or a valid full date/time
- away_end: empty or a valid full date/time

Valid Away date/time values continue to be normalized to timezone-aware ISO before persistence.

## Error handling

Invalid input remains on the EMS configuration form and receives a field-specific error. The submission is not stored when any Step 4A field is invalid.

## Explicitly deferred to Step 4B

Step 4A does not compare fields with each other. In particular:
- technical_min_soc_percent < max_soc_percent is not enforced yet.
- away_end > away_start is not enforced yet.
- Away start/end are not made mandatory based on the Away enable switch yet.

Those combination rules remain Step 4B.

## Preserved

- Existing Step 3A/3B/3C configuration behavior for valid values.
- Native 15 minute / 72 hour / 288 slot forecast architecture.
- Legacy Dummy OS EMS remains the physical battery controller.
- DOEMS physical_execution_authority remains false.

## Not included

- No planner or decision-engine changes.
- No Anker source mapping.
- No running startup gate.
- No Away/Presence profile switching.
- No plan-slot implementation.
- No physical battery service calls.

## Live validation target

Confirm valid boundary values still save, values below/above limits or on an invalid step are rejected, invalid Away date/time input is rejected, and valid values remain persistent after reopening Options.
