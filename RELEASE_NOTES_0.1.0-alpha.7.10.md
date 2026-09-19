# DOEMS 0.1.0-alpha.7.10 - G6 Step 3C EMS Time Mode Configuration

## Scope

Alpha7.10 publishes G6 Step 3C only. It extends the existing EMS Options screen from nine to thirteen settings with startup-delay and one explicit Away schedule window. This release is configuration-only and does not activate the startup gate, Away runtime, planner logic or physical battery execution.

## Added

- `startup_delay_seconds`
  - label: Startup delay
  - default 30 s
  - range 30-300 s
  - step 5 s
- `away_schedule_enabled`
  - label: Enable Away schedule
  - default false
- `away_start`
  - label: Away start
  - optional full date/time
  - default unset
- `away_end`
  - label: Away end
  - optional full date/time
  - default unset

The Away start/end values are stored as ISO datetimes with timezone information. If the Home Assistant selector supplies a local datetime without an offset, DOEMS attaches the configured Home Assistant timezone before persistence.

## Preserved

- Step 3A and Step 3B fields remain unchanged on the same EMS configuration screen.
- Native forecast architecture remains 15 minutes / 72 hours / 288 slots.
- Legacy Dummy OS EMS remains the physical battery controller and golden reference during G6.
- DOEMS physical execution authority remains disabled.

## Not included

- No running startup readiness gate.
- No Away/Presence runtime transitions or schedule execution.
- No planner or decision-engine changes.
- No Anker source mapping.
- No plan-slot implementation.
- No physical battery service calls or execution authority.
- No Step 4 validation rules yet; cross-field validation such as Away end after Away start remains deferred to Step 4B.

## Live validation target

After installation, confirm that the existing EMS Options screen contains all thirteen fields, that Startup delay defaults to 30 s and enforces 30-300 s, that the Away schedule toggle defaults off, that Away start/end can be entered as full date/time values and persist after reopening Options, and that no startup, profile, planner or physical battery action is triggered.
