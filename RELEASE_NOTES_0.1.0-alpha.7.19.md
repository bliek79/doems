# DOEMS 0.1.0-alpha.7.19 - G6 Step 5A Prices 76h Rolling Window Fix

## Scope

Alpha7.19 fixes the live-proven 287/288 EMS input regression without changing the 288-slot contract.

Alpha7.18 diagnostics showed that native slot 287 was missing only import_price and export_price. The Prices layer already retained a 76-hour / 304-slot buffer, but EMS consumed the already-trimmed 72-hour public timeline. When the EMS rolling window advanced one quarter before the next Prices refresh, the public timeline overlapped only 287 of the required 288 quarters.

## Fix

- Adds `DOEMSPricesManager.price_window(window_start=..., slot_count=...)`.
- The method selects an exact quarter-aligned window from the retained 304-slot / 76-hour price buffer.
- Missing buffer points remain explicit `kind=missing`; there is no padding, zero-fill, nearest-neighbour substitution or window shifting.
- `ems_live_input.py` now calculates one central `window_start = ceil_quarter(reference)` and requests exactly `FORECAST_SLOTS=288` prices from the 76-hour buffer.
- EMS no longer consumes `prices.timeline_slots` as its authoritative price input.
- The public 72-hour Prices timeline remains unchanged for UI/entity consumers.

## Regression coverage

The new regression test reproduces the live failure:
- price buffer starts on the previous quarter;
- the old public 288-slot timeline is therefore one quarter behind the current EMS rolling window;
- the 304-slot buffer still contains the new final quarter;
- EMS must receive 288/288 valid native slots;
- the final EMS quarter is present with valid import/export prices.

## Preserved contracts

- native forecast architecture: 15 minutes / 72 hours / 288 slots;
- Prices buffer: 76 hours / 304 slots;
- Alpha41 288-to-72 compatibility mapping unchanged;
- 288-slot fail-closed gate unchanged;
- copied Alpha76 decision logic unchanged;
- no Step 5B activation.

## Safety boundary

Unchanged:
- Prestart Validator not invoked;
- Safety Guard not invoked;
- Action Controller not invoked;
- Execution Controller not invoked;
- no battery control service calls;
- `physical_execution_authority=false`.

## Live validation target

After installing Alpha7.19:
- `sensor.doems_ems_shadow.input_contract_status` should become `ready` when all underlying sources are present;
- `native_valid_slot_count` should be 288;
- `invalid_slot_count` should be 0;
- Energy Need, Planner Preview, Plan72, Bridge, shadow Plan Store and Scheduler may then run again;
- all physical-execution boundary flags must remain false.

Step 5B remains blocked.
