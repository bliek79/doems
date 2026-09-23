# DOEMS 0.1.0-alpha.16 - Step 12.5 Execution Controller Shadow

## Scope
Step 12.5 adds a complete non-actuating shadow of the future automatic Execution Controller, including runtime safety, safe-return preview and planned-versus-actual audit.

## Added
- Stateful Execution Controller Shadow behind the Step 12.4 Automatic Execution Gate.
- Immutable frozen execution identity and action snapshot.
- Five-second read-only runtime monitor.
- Runtime checks for planner identity, mode, direction, power setpoint, opposite battery direction, battery power sources and SOC.
- Explicit warning when no device-status source is configured yet.
- Normal completion decisions for target SOC, minimum SOC, planned energy, planned window and max runtime.
- Emergency shadow-stop decisions for identity, mode, direction, setpoint, SOC and battery-power-source faults.
- Fixed safe-return preview: 0 W -> wait 1 second -> self_consumption.
- Planned-versus-actual run audit with power samples, energy, SOC, timing deltas, result and reason.
- Bounded in-memory run history and compact execution trace.
- Large shadow/audit attributes are excluded from Recorder state history.

## Safety boundary
Step 12.5 remains fully non-actuating:
- execution_controller_invoked=false
- mode_switch_performed=false
- direction_written=false
- power_setpoint_written=false
- safe_return_performed=false
- service_calls_performed=false
- physical_execution_authority=false
- no Home Assistant control service is called

The existing physical/legacy controller remains authoritative. Step 12.5 only observes what would happen if DOEMS had execution authority.

## Next
Step 12.6 remains closed: restart/recovery and final public observability acceptance are not part of this release.
