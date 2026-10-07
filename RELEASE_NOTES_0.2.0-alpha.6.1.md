# DOEMS 0.2.0-alpha.6.1 - Automatic Planner Runtime Fix

## Scope

This hotfix changes runtime orchestration only. The R5 automatic-planner policy from 0.2.0-alpha.6 remains unchanged.

### Live issue fixed

Home Assistant live validation of 0.2.0-alpha.6 showed that `sensor.doems_automatic_planner` could execute the complete 288-slot planner synchronously during entity state reads. One observed update blocked the Home Assistant MainThread for 123.024 seconds.

### Proven runtime pattern restored

The hotfix follows the proven Dummy OS Anker EMS Alpha81 runtime pattern:

- heavy planner work runs through `hass.async_add_executor_job(...)`, outside the Home Assistant event loop;
- one frozen input generation is computed at a time;
- only the newest generation may publish;
- stale generations are discarded;
- duplicate requests inside the same native quarter are suppressed with deterministic signatures;
- normal planner cadence is native 15-minute boundaries plus explicit forecast/manual/recovery events;
- ordinary battery SOC/power ticks do not start a heavy recomputation;
- capacity changes and battery readiness transitions do;
- the complete planner result is cached atomically;
- planner sensors read only the cached snapshot and never execute planner policy;
- the compact SOC timeline is prepared in the background worker instead of being rebuilt by the sensor.

### R5 policy unchanged

The following remain exactly as in 0.2.0-alpha.6:

- native 15 minutes / 72 hours / 288 slots;
- manual commitments have hard priority;
- live battery-capacity sensor is authoritative;
- 5% technical minimum + 5% software reserve = 10% normal planner floor;
- 92% / 92% charge/discharge efficiency;
- configurable charge/discharge limits, default 3500 W;
- normal arbitrage remains separate from peak sale;
- configurable minimum trade margin, default 0.10 EUR/kWh;
- configurable peak-sale trigger, default 0.50 EUR/kWh;
- no automatic Plan Store writes;
- no Scheduler;
- no Safety/Prestart execution chain;
- no physical battery commands;
- `physical_execution_authority=false`.

The alpha.6 policy file `automatic_planner_model.py` is byte-frozen by CI using its Git blob identity.

### Live validation gate

R5 remains open until 0.2.0-alpha.6.1 is validated live in Home Assistant. R6 stays blocked.
