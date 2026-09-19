# DOEMS 0.1.0-alpha.7.12 - G6 Step 4B EMS Combination Validation

## Scope

Alpha7.12 publishes G6 Step 4B only. It adds cross-field validation on top of the already live-green Step 4A individual field validation.

## Combination validation

The EMS options flow now checks these relationships before saving:

- technical_min_soc_percent must be strictly lower than max_soc_percent.
- When away_schedule_enabled is true, away_start is required.
- When away_schedule_enabled is true, away_end is required.
- When away_schedule_enabled is true, away_end must be strictly later than away_start.
- When away_schedule_enabled is false, Away start/end remain optional and their relative order is not enforced.

The SOC relationship is kept as a defensive invariant. With the current Step 4A field ranges (technical minimum SOC 0-30% and maximum SOC 50-100%), normal UI input already satisfies this relationship, but the backend still protects the invariant.

## Error handling

Step 4A field validation runs first. Only when all individual fields are valid are Away date/time values normalized to timezone-aware ISO values and Step 4B combination rules evaluated.

If a Step 4B combination is invalid:
- the EMS Options form remains open;
- a field-specific error is shown;
- the submitted configuration is not stored.

## Preserved

- All Step 4A individual validation rules.
- Existing Step 3A/3B/3C configuration behavior for valid values.
- Native 15 minute / 72 hour / 288 slot architecture.
- Legacy Dummy OS EMS remains the physical battery controller.
- DOEMS physical_execution_authority remains false.

## Not included

- No planner or decision-engine changes.
- No Anker source mapping.
- No running startup gate.
- No Away/Presence runtime or automatic profile switching.
- No plan-slot implementation.
- No physical battery service calls.

## Live validation target

Verify in Home Assistant that:
- Away schedule off can be saved with empty Away start/end.
- Away schedule on with a missing start is rejected.
- Away schedule on with a missing end is rejected.
- Away schedule on with end equal to or earlier than start is rejected.
- Away schedule on with end later than start is accepted and persists after reopening Options.

The SOC relation remains covered by backend tests because the current individual field ranges prevent creating an invalid SOC pair through the normal UI.
