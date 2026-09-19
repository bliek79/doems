# DOEMS 0.1.0-alpha.7.8 - G6 Step 3A EMS Configuration

## Scope

Alpha7.8 publishes G6 Step 3A only: the first DOEMS EMS configuration surface. It adds configuration storage and an Options Flow screen for five battery and power settings without changing EMS decision logic or introducing physical battery execution.

## Added

- Optional `ems_enabled` module toggle in DOEMS Options.
- EMS battery settings screen with:
  - `battery_capacity_kwh`
  - `technical_min_soc_percent`
  - `max_soc_percent`
  - `max_charge_power_w`
  - `max_discharge_power_w`
- Current migration defaults: 7.2 kWh, 5%, 100%, 3200 W charge and 3200 W discharge.
- Hard configurable charge/discharge ceiling: 3500 W.

## Not included

- No EMS planner or decision-engine changes.
- No Anker source mapping.
- No startup readiness-gate execution.
- No Away runtime/profile implementation.
- No plan-slot implementation.
- No physical battery service calls or execution authority.
- No Step 3B or Step 3C settings yet.

## Preserved contracts

- Native forecast architecture remains 15 minutes / 72 hours / 288 slots.
- Energy, Solar and Prices runtime behavior remains unchanged.
- Legacy Dummy OS EMS remains the physical battery controller and golden reference during G6.
- DOEMS remains shadow-only for EMS migration; physical execution authority is not introduced.
- README remains intentionally unchanged and is handled separately.

## Live validation target

After installation, confirm that DOEMS Options exposes `Enable EMS configuration`, that enabling it opens only the five-field Step 3A form, that values save and restore correctly, and that no new planner or physical battery action occurs.
