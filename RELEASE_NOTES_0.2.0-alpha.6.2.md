# DOEMS 0.2.0-alpha.6.2 - Price Window Alignment Fix

## Scope

This is a targeted R5 alignment hotfix. It does not change the R5 planner policy, manual planning, the Plan Store, Scheduler, Safety/Prestart, or physical execution.

## Live issue fixed

After 0.2.0-alpha.6.1 removed the Home Assistant MainThread regression, live validation showed the automatic planner correctly failing closed on:

- `price_slot_286_missing`
- `price_slot_287_missing`

Prices P4 already keeps a native 76-hour / 304-slot internal buffer, but its public 288-slot timeline is cut at the time of the 30-minute Prices refresh. The R5 planner advances on its own native quarter reference, so the last shifted quarters could fall outside that older public presentation window.

## Targeted correction

- Prices P4 now exposes a read-only planner window selector.
- For the planner reference it selects exactly 288 native quarters from the existing 304-slot buffer.
- R5 uses that aligned window with the same planner reference used for its Energy route.
- The public Prices timeline/dashboard contract is unchanged.
- No price is invented, extended, interpolated, or copied forward.
- A genuinely missing source quarter still remains a `price_slot_<n>_missing` blocker.

## Unchanged R5 policy and control path

- native 15 minutes / 72 hours / 288 slots;
- manual commitments retain hard priority;
- live battery capacity remains authoritative;
- 5% technical minimum + 5% software reserve = 10% planner floor;
- 92% / 92% efficiencies;
- configurable charge/discharge limits, default 3500 W;
- normal arbitrage and peak-sale policy unchanged;
- no automatic Plan Store writes;
- no Scheduler;
- no Safety/Prestart execution chain;
- no mode switch;
- no physical battery commands;
- `physical_execution_authority=false`.

The R5 policy file `automatic_planner_model.py` remains byte-frozen in CI.

R6 stays blocked until this release is live validated.
