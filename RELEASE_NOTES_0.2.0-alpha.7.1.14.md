# DOEMS 0.2.0-alpha.7.1.14 - R6 to R7 Quarter-Hour Contract Fix

**Scope:** authorized corrective R7 integration patch. **R0-R6 remain LIVE GROEN / frozen.** R7 remains LIVE VALIDATIE OPEN until Home Assistant checks and explicit user acceptance. R8 is not opened.

## Corrected behavior

R6 correctly emits a contiguous native 15-minute (0.25 h) automatic charging/discharging segment. In alpha.7.1.13 the Plan Store's shared Manual validator and R7 Prestart imposed a 30-minute (0.5 h) minimum, producing `max_runtime_out_of_range` on valid R6 proposals.

- Added one pure, internal R6 Automatic plan contract module (not a new HA entity, helper, slot or planner). It accepts 0.25-12.0 h in exact 15-minute increments, checks coherent start/end time and duration, permitted action, power, target SOC and start margin.
- The existing Plan Store displays and validates `origin=automatic_72h_planner` using this automatic contract. Its user-facing `schedule_blockers` no longer incorrectly applies Manual's future-start rule during an automatic start window.
- The R7 Prestart gate and the Plan Store's guarded automatic `concept -> pending` transition use that same contract. They still require live Safety and Prestart approval, unchanged identity/signature/revision and the approved `start_time <= now <= start_time + max_start_delay_min` window.
- Manual keeps the original 0.5-12 h validity, manual ownership, explicit scheduling button, expiry, service behavior and precedence. R6 288-quarter bridge/optimization is unchanged.
- New end-to-end tests validate a real 0.25 h R6 proposal from the 288-slot source through Plan Store, R7 selection/Safety/Prestart, guarded pending, restart/persistence and expiry/audit, plus malformed durations, Manual 0.25 h rejection and no execution capability.

## Safety and release boundary

- Architecture remains **15 min / 72 hours / 288 quarters**. Dynamic battery capacity from its configured live sensor. No hardcoded capacity.
- This release **does not** alter physical battery commands, battery operating mode, automatic execution switch, R8, or existing R5 policy.
- `physical_execution_enabled=false` and `execution_authority=false` remain mandatory.
- The permanent public sensor is `sensor.doems_scheduler_status`; no development-phase prefixes were introduced.
- CI must pass the full regression suite and protect frozen nonaffected R0-R6 file hashes before publication.

## After installation

Inspect `sensor.doems_scheduler_status` and `sensor.doems_plan_1_status`/`2`/`3` with an automatic native 15-minute proposal. Verify there is no `max_runtime_out_of_range`, that due Safety/Prestart can approve a valid proposal, that Manual is protected and execution remains off. Automatic expiry remains governed by R6. Publication does **not** constitute R7 live acceptance.

Rollback: 0.2.0-alpha.7.1.13.
