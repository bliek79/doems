# DOEMS 0.1.0-alpha.20 - Cheapest Energy Safety Planner

## Scope
Alpha20 changes only the production EMS planning policy. The frozen Step 13/G5 Alpha76 parity reference remains unchanged and Step14/G6 remains closed.

## Core rule
Within the rolling 72-hour / 288-slot architecture, DOEMS chooses the cheapest technically feasible way to cover forecast household demand while retaining the existing compact safety contract:
- 5% technical minimum SOC;
- +7% software reserve;
- 12% planning target.

Solar stays the first source. The first two-hour usable-solar block remains useful diagnostic context but no longer ends the economic calculation.

## Changed
- The complete rolling 72-hour route is evaluated, including the period after the next usable-solar block.
- A horizon with no usable-solar block remains planable instead of blocking the policy.
- If projected SOC would fall below the 12% planning target, DOEMS searches all technically valid charge hours up to that deadline and selects the cheapest available import energy.
- A later cheaper charge window wins when the battery can safely reach it.
- If that later window cannot be reached, an earlier window buys only the bridge energy that is necessary.
- A cheap window may charge to 100% when later forecast demand needs the full stored energy.
- Charge/discharge efficiency remains part of the economic context (default 92% / 92%).
- Normal self_consumption is projected physically down to the configured technical minimum; the 12% target is achieved by planned safety charging rather than a fictitious hold.
- Trading remains secondary to solar and household safety coverage.

## Compactness
No public entity, charge stream or purpose was added.
The existing categories remain:
- veiligheidsladen
- handelsladen
- zonneladen
- woning_ontladen

The rejected `zelfconsumptie_bijladen`, `grid_support_charge` and `charge_from_grid_support_kwh` contracts are not present.

## Frozen G5 boundary
- `ems_alpha76/*` remains untouched.
- `ems_alpha76_adapter.py` remains the frozen G5 compatibility path.
- The production runtime uses the new compact `ems_policy_alpha20.py`.
- G5 remains diagnostic/non-actuating and does not open G6.
- `physical_execution_authority=false` remains unchanged.

## Version
`0.1.0-alpha.20`
