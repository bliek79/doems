# DOEMS 0.1.0-alpha.7.14 - G6 Step 5A EMS Settings Config Reads

## Scope

Alpha7.14 implements the safe first build part of G6 Step 5A: one immutable, typed EMSSettings snapshot is created from the validated DOEMS EMS Options and attached to the DOEMS runtime when EMS is enabled.

This release deliberately does not copy or activate the legacy Alpha76 planner/EMS decision core. The current DOEMS main branch does not yet contain that core, and copying the legacy hourly planner into DOEMS would violate the fixed native 15-minute / 72-hour / 288-slot architecture. Therefore this release establishes the configuration-read contract without changing decision behavior.

## EMSSettings contract

The runtime snapshot reads exactly these ten static EMS Options:

- battery_capacity_kwh
- technical_min_soc_percent
- max_soc_percent
- max_charge_power_w
- max_discharge_power_w
- software_reserve_percent
- charge_efficiency_percent
- discharge_efficiency_percent
- minimum_trade_margin_eur_per_kwh
- startup_delay_seconds

Reads use the persisted config_entry.options values. Existing DOEMS defaults are used only when a key is absent.

The snapshot is immutable and contains no Away/Presence runtime state.

## Runtime binding

When EMS is enabled:
- EMSSettings.from_options(entry.options) is evaluated once during entry setup;
- the resulting immutable snapshot is stored in the DOEMS entry runtime data;
- sensor.doems_ems_settings exposes the ten values for live validation.

The diagnostic sensor also reports:
- settings_source=config_entry_options
- settings_snapshot_immutable=true
- startup_delay_runtime_gate_active=false
- planner_logic_active=false
- physical_execution_authority=false

## Preserved safety and architecture

- Native forecast architecture remains 15 minutes / 72 hours / 288 slots.
- No planner or decision formula is added or changed.
- No legacy hourly planner is copied into the active DOEMS runtime.
- startup_delay_seconds is read but does not yet activate a startup gate.
- Away/Presence remains owned by PresenceStore entities.
- No Anker source mapping is added.
- No plan-slot execution is added.
- No physical battery service calls are added.
- Legacy Dummy OS EMS remains the physical controller.
- physical_execution_authority remains false.

## Step 5A status after this release

The config-read layer is built and publishable. The remaining Step 5A work is the actual consumer wiring when the frozen EMS decision core is ported into DOEMS in a way that preserves the required native 15-minute / 72-hour / 288-slot architecture. Step 5B behavior parity must not start before that consumer wiring exists.

## Live validation target

After installing Alpha7.14:
- confirm sensor.doems_ems_settings exists when EMS is enabled;
- confirm all ten attributes exactly match the saved EMS Options;
- change one valid EMS Option, save/reload, and confirm the sensor reflects only that changed value;
- confirm startup_delay_runtime_gate_active=false;
- confirm planner_logic_active=false;
- confirm physical_execution_authority=false.
