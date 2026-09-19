# DOEMS 0.1.0-alpha.7.9 - G6 Step 3B EMS Configuration

## Scope

Alpha7.9 publishes G6 Step 3B only. It extends the existing EMS Options screen from five to nine settings by adding reserve, efficiency and minimum trade-margin configuration. It does not change planner logic or introduce physical battery execution.

## Added

- `software_reserve_percent`
  - default 7%
  - range 0-30%
  - step 1%
- `charge_efficiency_percent`
  - default 92%
  - range 50-100%
  - step 1%
- `discharge_efficiency_percent`
  - default 92%
  - range 50-100%
  - step 1%
- `minimum_trade_margin_eur_per_kwh`
  - default EUR 0.10/kWh
  - range EUR 0.00-1.00/kWh
  - step EUR 0.01/kWh

The four Step 3B fields are shown on the same EMS configuration screen as the five Step 3A fields.

## Preserved

- Step 3A battery capacity, SOC and charge/discharge power settings remain unchanged.
- Native forecast architecture remains 15 minutes / 72 hours / 288 slots.
- Legacy Dummy OS EMS remains the physical battery controller and golden reference during G6.
- DOEMS physical execution authority remains disabled.

## Not included

- No planner or decision-engine changes.
- No Anker source mapping.
- No startup readiness-gate implementation.
- No Away/Presence runtime changes.
- No plan-slot implementation.
- No physical battery service calls or execution authority.
- No Step 3C settings yet.

## Live validation target

After installation, confirm that the existing EMS Options screen contains all nine fields, that the four new Step 3B defaults/ranges are correct, that changed values save and are restored when Options is reopened, and that no new physical battery action occurs.
