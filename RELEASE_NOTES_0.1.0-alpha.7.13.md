# DOEMS 0.1.0-alpha.7.13 - G6 Away Presence Entities

## Scope

Alpha7.13 implements the approved Away architecture correction.

Away and profile control are removed from Options and moved to Home Assistant runtime entities backed by one persistent DOEMS PresenceStore.

## New Presence entities

- select.doems_presence_profile
- switch.doems_away_schedule_enabled
- datetime.doems_away_start
- datetime.doems_away_end
- binary_sensor.doems_away_active
- binary_sensor.doems_away_schedule_valid
- sensor.doems_presence_context

The select represents the manual profile choice. The effective profile is resolved centrally by PresenceStore and exposed by the context/diagnostic entities.

## Presence contract

Canonical profile states remain:
- normal
- away
- unclassified

Priority remains:
1. manual override inside an active Away window;
2. valid active Away schedule;
3. manual profile outside an active schedule;
4. restored persistent state;
5. unclassified when the state cannot be resolved safely.

Invalid enabled Away scheduling fails closed to unclassified. There is no silent fallback to normal.

PresenceStore persists manual/effective profile, previous profile, pre-schedule profile, schedule window state, override state, timestamps, source/reason and blockers. Schedule start/end boundaries are actively scheduled and re-evaluated at runtime.

## Energy Forecast coupling

The former Energy Profile select is replaced by the shared Presence Profile select. When Energy Forecast is enabled, its coordinator follows PresenceStore effective profile. Profile changes continue to preserve quarter-learning integrity.

The former initial learning-profile Option is migration-only and is removed from Options when saved.

## Away migration from Alpha7.10-7.12

The old Options keys:
- away_schedule_enabled
- away_start
- away_end

are retained only as legacy migration inputs. PresenceStore reads them once when no PresenceStore exists yet. Subsequent Options saves remove those legacy keys.

## EMS Options after migration

EMS Options now contains only static configuration:
- battery capacity
- technical minimum SOC
- maximum SOC
- maximum charge power
- maximum discharge power
- software reserve
- charge efficiency
- discharge efficiency
- minimum trade margin
- startup delay

Step 4A individual field validation remains intact. Step 4B SOC combination validation remains intact. Away validation now belongs to PresenceStore runtime state instead of EMS Options.

## Safety

- No planner or decision-engine changes.
- No Anker source mapping.
- No battery startup execution gate.
- No plan-slot implementation.
- No physical battery service calls.
- Legacy Dummy OS EMS remains the physical controller.
- physical_execution_authority remains false.

## Live validation target

After installing Alpha7.13 verify:
- the 7 Presence/Away entities exist;
- EMS Options no longer shows Away enable/start/end;
- Energy Forecast Options no longer shows an initial profile selector;
- manual normal/away changes update Presence Context;
- enabling an incomplete/invalid Away schedule yields unclassified with blockers;
- a valid future/current Away window becomes schedule-valid;
- an active valid window makes Away active;
- a manual profile change during an active window becomes an override and is not immediately reasserted;
- state persists across Home Assistant restart;
- no physical battery action is performed by DOEMS.
