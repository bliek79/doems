# DOEMS 0.2.0-alpha.6 - Automatic Planner Shadow

## R5 scope

This release restores the automatic planning decision layer on the proven native 15-minute / 72-hour / 288-slot route. It remains observational only.

### Planner contract
- Manual commitments are applied first and cannot be overwritten by automatic planning.
- Live battery-capacity input remains authoritative; there is no fixed 7.1 kWh fallback.
- Technical minimum SOC is 5% and software reserve is 5%, giving a normal planner floor of 10%.
- Charge/discharge efficiency remains 92% / 92%.
- Automatic charge and discharge power default to 3500 W and are configurable in DOEMS options.
- Normal arbitrage keeps a configurable minimum margin, default 0.10 EUR/kWh.
- Peak-sale evaluation has a separate configurable trigger, default 0.50 EUR/kWh export price.
- Peak sale only uses energy that remains free after protecting the planner floor, home demand, manual commitments and the route to a later favorable PV or grid recharge opportunity.
- Usable-solar detection uses the historical two-consecutive-hour rule mapped to eight native 15-minute quarters.

### Public validation surfaces
- `sensor.doems_automatic_planner`
- `sensor.doems_automatic_soc_projection_timeline`
- Existing `sensor.doems_ems_plan72_hours` identity now exposes the combined R5 shadow route for dashboard compatibility.

### Hard R5 boundary
- No automatic Plan Store writes.
- No Scheduler.
- No Safety/Prestart execution chain.
- No physical battery commands.
- `physical_execution_authority=false`.

R6 automatic slot alignment remains blocked until R5 is live validated.
