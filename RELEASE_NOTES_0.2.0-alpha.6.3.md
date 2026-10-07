# DOEMS 0.2.0-alpha.6.3 - R5 Planner Parity Fix

## Scope

This remains an R5 shadow-planner release. It does not open R6 and it does not change the control path.

The release keeps the proven alpha.6.1 cached/executor runtime and the alpha.6.2 304-slot price-buffer alignment. It corrects only planner semantics that were still different from the proven Dummy OS Anker EMS Alpha24.4 route.

## Historical parity restored

### Usable solar

The historical rule is restored functionally on the native quarter-hour route:

- aggregate native quarters into complete clock hours only for the usable-solar decision;
- a clock hour is usable when total solar for that full hour is at least total forecast home consumption for that full hour;
- the usable-solar point is the first of two consecutive full clock hours that both satisfy that condition;
- partial first/last clock hours do not qualify.

The underlying architecture remains native 15 minutes / 72 hours / 288 slots.

### Dynamic reserve

The automatic route now calculates a dynamic protected reserve toward the next demonstrable usable-solar block.

The protected requirement contains:

- technical minimum SOC;
- configured software reserve;
- forecast home deficit until the next usable-solar block;
- discharge efficiency.

When no next usable-solar block is demonstrable in the remaining forecast, the planner follows the Alpha24.4 fallback and returns to the normal base floor instead of accumulating the complete remainder of the 72-hour home forecast.

### Safety charging

Safety charging no longer acts as generic 72-hour SOC top-up.

The planner protects the dynamic reserve and adds only the energy required to prevent a reserve breach, using the cheapest technically feasible free native quarters before the breach.

Safety remains separate from trade.

### Safety plus trade

A safety requirement somewhere in the 72-hour route no longer disables ordinary arbitrage for the entire route.

After required safety energy is protected, the remaining free route can still be evaluated for:

- ordinary arbitrage using the configured minimum margin;
- peak sale using the configured peak-sale threshold and protected route to a favorable recharge opportunity.

Manual commitments retain hard priority.

## Existing R5 contract retained

- live battery capacity sensor remains authoritative;
- no fixed 7.1 kWh planner capacity;
- charge/discharge efficiency remains 92% / 92%;
- software reserve default remains 5%;
- technical minimum remains 5%;
- configured charge/discharge limits remain user options with 3500 W defaults and 3500 W upper bound;
- minimum normal trade margin remains configurable, default 0.10 EUR/kWh;
- peak sale threshold remains configurable, default 0.50 EUR/kWh;
- no automatic Plan Store writes;
- no Scheduler;
- no Safety/Prestart execution chain;
- no battery mode switch;
- no physical battery commands;
- physical_execution_authority=false.

## Existing Home Assistant options

Home Assistant preserves previously stored integration options. An installation that still has the older 7% software reserve and 3200 W charge/discharge limits will continue to show those values after updating.

For R5 live validation set the DOEMS options explicitly to:

- software reserve: 5%;
- maximum automatic charge power: 3500 W;
- maximum automatic discharge power: 3500 W.

This release deliberately does not silently overwrite user configuration.

## Live validation gate

R6 remains blocked until live Home Assistant validation proves:

- Automatic Planner valid=true;
- Automatic SOC Projection Timeline has 288 points;
- base planner floor is 10% with the configured 5% software reserve;
- usable-solar diagnostics use the two-consecutive-full-clock-hours rule;
- dynamic reserve can rise before a future usable-solar block and falls back to the base floor as appropriate;
- incomplete solar horizon does not create an artificial 100% reserve;
- safety energy is limited to required reserve protection;
- ordinary arbitrage/peak-sale evaluation can still occur on the remaining free route;
- physical_execution_authority remains false.
