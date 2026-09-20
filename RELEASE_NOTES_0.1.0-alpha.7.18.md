# DOEMS 0.1.0-alpha.7.18 - G6 Step 5A Forecast Contract Diagnostics

## Scope

Alpha7.18 adds targeted diagnostics for the live fail-closed forecast contract observed after Alpha7.17.

The 288-slot requirement and all planner behavior remain unchanged. This release only makes an invalid native quarter explainable and keeps the EMS Settings status synchronized with the live shadow runtime.

## Added

- Native-slot diagnostics in `ems_input_contract.py`
  - `missing_inputs` per native quarter;
  - `invalid_slot_count`;
  - `first_invalid_slot`;
  - `last_invalid_slot`;
  - `invalid_slots` with slot index, exact quarter start and missing input names.
- Missing inputs are reported using the existing validation sources:
  - `home`
  - `solar`
  - `import_price`
  - `export_price`
- `sensor.doems_ems_shadow` exposes the compact invalid-slot diagnostics.
- `sensor.doems_ems_settings` now listens to the shadow runtime so `shadow_runtime_status` follows live runtime changes instead of remaining stale.

## Unchanged fail-closed gate

The runtime still stops before Energy Need when any of these conditions fail:
- input contract status is not `ready`;
- `native_valid_slot_count != 288`;
- transport row count is not exactly 72.

No missing value is repaired, zero-filled, padded or nearest-neighbour substituted.

## Safety boundary

Unchanged:
- Prestart Validator not invoked;
- Safety Guard not invoked;
- Action Controller not invoked;
- Execution Controller not invoked;
- no battery control service calls;
- `physical_execution_authority=false`.

## Live validation target

After installing Alpha7.18, reproduce or observe the 287/288 condition and inspect `sensor.doems_ems_shadow`.

Expected diagnostics:
- `invalid_slot_count=1` when exactly one quarter is incomplete;
- `first_invalid_slot` and `last_invalid_slot` identify the same exact quarter;
- `invalid_slots` identifies the exact `missing_inputs`;
- runtime remains `waiting_for_complete_forecast` until all 288 native quarters are valid;
- Energy Need / Plan72 / Bridge / Plan Store / Scheduler remain blocked while incomplete;
- `sensor.doems_ems_settings.shadow_runtime_status` matches the current shadow runtime state.

Step 5B remains blocked.
