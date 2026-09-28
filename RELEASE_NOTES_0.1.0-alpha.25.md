# DOEMS 0.1.0-alpha.25 - Solar Array Performance Factor

## Purpose

Alpha25 makes the static Solar performance/loss factor configurable per
provider-neutral PV array while keeping the existing physical forecast,
inverter-group AC capping and native time contract intact.

This release does not add Local Shading / Obstruction Learning. Static array
performance and future time-/sun-position-dependent shading correction remain
strictly separate layers.

## Array configuration

Each PV array now stores a static `performance_factor`.

The Options flow exposes this as:

- **Performance factor / static yield factor (%)**
- default: **90%**
- internal representation: **0.90**

Existing installations that do not yet contain the new array field automatically
use 0.90, preserving the Alpha24 forecast behavior until the user explicitly
changes a factor.

## Forecast calculation

For every array the physical forecast now applies:

`GTI / 1000 x array DC kWp x array performance factor`

The result then enters the unchanged inverter-group logic:

1. calculate each member array with its own static factor;
2. sum the uncapped member power per inverter group;
3. apply the existing group AC cap when required;
4. scale member arrays proportionally exactly as before;
5. convert the final 15-minute power to energy.

The native architecture remains exactly 15 minutes / 72 hours / 288 slots.

## Diagnostics and reproducibility

Solar Foundation schema version is now 2.

The normalized Foundation snapshot stores a performance factor on every array.
Missing legacy values are materialized as 0.90. The factor is part of the
topology/configuration signature so a factor change produces a new reproducible
forecast configuration identity.

The Solar forecast model attributes expose:

- `performance_factor`: the common factor when all arrays are equal, otherwise
  `mixed`;
- `array_performance_factors`: exact factor per stable array ID;
- `performance_factor_semantics=static_per_array_before_group_ac_cap`.

## Google Sheets

No new Solar Sheet columns are required for Alpha25.

The existing **Forecast performance factor** column remains usable:
- one numeric value when all arrays use the same factor;
- `mixed` when arrays differ.

The exact per-array factors are preserved in the existing
**Forecast model attributes JSON** field, so every stored forecast remains
reproducible without expanding the current 112-column sheet contract.

## Explicit shading boundary

Alpha25 does **not** implement:

- Local Shading / Obstruction Learning;
- sun-position binning;
- seasonal shading correction;
- automatic performance calibration;
- corrected Solar forecasts;
- automatic model promotion;
- time-dependent loss factors.

The raw physical Solar forecast remains the permanent independent reference.
A later shading observer may only run parallel to it and requires separate
A/B evidence before any corrected forecast can become an EMS candidate.

## Validation

Regression coverage verifies:

- missing factor -> 0.90 backward-compatible behavior;
- different factors per array;
- 0.82 and 0.67 calculations;
- factor application before group AC capping;
- unchanged proportional AC-cap scaling;
- array and total consistency;
- native 15-minute energy conversion;
- exact 72-hour / 288-slot timeline;
- factor persistence in the normalized Foundation snapshot;
- factor changes alter the configuration signature;
- percentage UI/translations are present;
- shading-learning remains absent from the runtime.

## Safety

Unchanged:

- no battery-control service call is added;
- no planner policy is changed;
- no execution authority is added;
- `physical_execution_authority=false`;
- Anker EMS remains the separate physical battery controller until a later
  explicitly approved cutover.
