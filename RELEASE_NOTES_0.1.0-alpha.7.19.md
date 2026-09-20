# DOEMS 0.1.0-alpha.7.19 - G6 Step 5A Prices 76h Rolling Window Fix

## Scope

Alpha7.19 fixes the live 287/288 EMS input regression by using the existing 76-hour Prices buffer as intended.

The bug was not missing market data. EMS consumed the already-cut public 72-hour `prices.timeline_slots`. When the EMS rolling `window_start` advanced by one quarter before the next Prices refresh, the public timeline overlapped only 287 of the required 288 EMS quarters and the final import/export price became missing.

## Fix

- `DOEMSPricesManager.price_window(...)` now exposes an exact quarter-aligned rolling window from the retained 304-slot / 76-hour price buffer.
- EMS computes one central `window_start = ceil_quarter(reference)`.
- EMS now selects exactly 288 price quarters from the 76-hour buffer using that same `window_start`.
- EMS no longer consumes `prices.timeline_slots` as its definitive price input.
- Missing buffer points remain explicit missing slots. No shifting, padding, zero-fill or nearest-neighbour substitution is introduced.

## Preserved contracts

- Prices internal buffer remains 76 hours / 304 native quarters.
- Public Prices timeline remains 72 hours / 288 quarters.
- EMS remains native 15 minutes / 72 hours / 288 quarters.
- Alpha41 288 -> 72 rolling compatibility mapping is unchanged.
- The fail-closed gate still requires exactly 288 valid native quarters before Energy Need / Planner Preview / Plan72 / Bridge / Plan Store / Scheduler may run.
- Price calculation, tariffs, provider priority and import/export semantics are unchanged.

## Safety boundary

Unchanged:
- Prestart Validator not invoked;
- Safety Guard not invoked;
- Action Controller not invoked;
- Execution Controller not invoked;
- no battery control service calls;
- physical_execution_authority=false.

## Live validation target

After installing Alpha7.19:
- `sensor.doems_ems_shadow.input_contract_status=ready`;
- `native_valid_slot_count=288`;
- `invalid_slot_count=0`;
- Energy Need, Planner Preview and Plan72 populate again;
- Bridge / shadow Plan Store / Scheduler may populate according to the actual Plan72;
- all physical execution flags remain false.

Step 5B remains blocked.
