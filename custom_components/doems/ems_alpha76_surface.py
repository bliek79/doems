"""Compact Alpha76-compatible EMS control surface for DOEMS.

The source integration exposes many individual EMS entities. DOEMS already has
native Forecast/Plan72 entities, so this compatibility surface restores the
missing control/safety/execution entities without duplicating the full forecast
surface. These entities are read-only views; they never participate in
decisions or physical writes.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_INSTANCE_NAME,
    DEFAULT_INSTANCE_NAME,
    DEVICE_IDENTIFIER,
    DOMAIN,
    NAME,
    VERSION,
)
from .ems_runtime import DOEMSEMSRuntime


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
        name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
        manufacturer=NAME,
        model="Energy Management System",
        sw_version=VERSION,
    )


class _RuntimeEntity:
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, entry: ConfigEntry, runtime: DOEMSEMSRuntime) -> None:
        self.runtime = runtime
        self._remove_listener: Callable[[], None] | None = None
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.runtime.async_add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


_BINARY_DEFS: tuple[tuple[str, str, Callable[[dict[str, Any]], bool]], ...] = (
    ("sources_available", "DOEMS EMS Sources Available", lambda d: all(
        d.get(k) is not None for k in ("soc", "device_status", "charge_power_w", "discharge_power_w", "operating_mode")
    )),
    ("control_available", "DOEMS EMS Control Available", lambda d: all(
        d.get(k) is not None for k in ("operating_mode", "action_direction", "power_setpoint_w")
    )),
    ("forecast_sources_available", "DOEMS EMS Forecast Sources Available", lambda d: bool(d.get("forecast_ready"))),
    ("scheduler_ready", "DOEMS EMS Scheduler Ready", lambda d: bool(d.get("scheduler_ready"))),
    ("safety_safe", "DOEMS EMS Safety Safe", lambda d: bool(d.get("safety_safe"))),
    ("controller_ready", "DOEMS EMS Controller Ready", lambda d: bool(d.get("controller_ready"))),
    ("physical_test_active", "DOEMS EMS Physical Test Active", lambda d: bool(d.get("physical_test_active"))),
    ("execution_active", "DOEMS EMS Execution Active", lambda d: bool(d.get("execution_active"))),
    ("planner_safety_charge_needed", "DOEMS EMS Safety Charge Needed", lambda d: bool(d.get("planner_preview_safety_charge_needed"))),
    ("planner_trade_charge_candidate", "DOEMS EMS Trade Charge Candidate", lambda d: bool(d.get("planner_preview_trade_charge_candidate"))),
    ("planner_discharge_possible", "DOEMS EMS Discharge Possible", lambda d: bool(d.get("planner_preview_discharge_possible"))),
    ("planner_solar_charge_delay", "DOEMS EMS Solar Charge Delay", lambda d: bool(d.get("planner_preview_solar_charge_delay"))),
    ("planner_trade_profitable", "DOEMS EMS Trade Profitable", lambda d: bool(d.get("planner_preview_trade_profitable"))),
    ("auto_plan_72h_valid", "DOEMS EMS Plan72 Valid", lambda d: bool(d.get("auto_plan_72h_valid"))),
    ("auto_plan_72h_execution_buffer_safe", "DOEMS EMS Plan72 Execution Buffer Safe", lambda d: bool(d.get("auto_plan_72h_execution_buffer_safe"))),
    ("auto_bridge_valid", "DOEMS EMS Action Bridge Valid", lambda d: bool(d.get("auto_bridge_valid"))),
    ("automatic_execution_ready", "DOEMS EMS Automatic Execution Ready", lambda d: bool(d.get("auto_shadow_technical_ready"))),
)


class DOEMSAlpha76BinarySensor(_RuntimeEntity, BinarySensorEntity):
    def __init__(
        self,
        entry: ConfigEntry,
        runtime: DOEMSEMSRuntime,
        key: str,
        name: str,
        value_fn: Callable[[dict[str, Any]], bool],
    ) -> None:
        super().__init__(entry, runtime)
        self.key = key
        self.value_fn = value_fn
        self._attr_name = name
        self._attr_unique_id = f"doems_alpha76_{key}"
        self._attr_suggested_object_id = f"doems_ems_{key}"

    @property
    def is_on(self) -> bool:
        return bool(self.value_fn(self.runtime.data))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.runtime.data
        if self.key == "automatic_execution_ready":
            return {
                "armed": d.get("auto_shadow_armed", False),
                "status": d.get("auto_shadow_status"),
                "blockers": d.get("auto_shadow_blockers", []),
                "warnings": d.get("auto_shadow_warnings", []),
                "selected_slot": d.get("auto_shadow_selected_slot"),
                "action": d.get("auto_shadow_action"),
                "purpose": d.get("auto_shadow_purpose"),
                "power_w": d.get("auto_shadow_power_w"),
                "target_soc": d.get("auto_shadow_target_soc"),
            }
        if self.key == "execution_active":
            return {
                "status": d.get("execution_status"),
                "reason": d.get("execution_reason"),
                "slot": d.get("execution_slot"),
                "action": d.get("execution_action"),
                "power_w": d.get("execution_power_w"),
                "target_soc": d.get("execution_target_soc"),
                "remaining_s": d.get("execution_remaining_s"),
                "last_result": d.get("execution_last_result"),
            }
        if self.key == "physical_test_active":
            return {
                "status": d.get("physical_test_status"),
                "reason": d.get("physical_test_reason"),
                "power_w": d.get("physical_test_power_w"),
                "remaining_s": d.get("physical_test_remaining_s"),
                "last_result": d.get("physical_test_last_result"),
            }
        if self.key == "scheduler_ready":
            return {
                "selected_slot": d.get("scheduler_selected_slot"),
                "selected_action": d.get("scheduler_selected_action"),
                "selected_execution_mode": d.get("scheduler_selected_execution_mode"),
                "selected_start_time": d.get("scheduler_selected_start_time"),
            }
        if self.key == "safety_safe":
            return {
                "status": d.get("safety_status"),
                "reason": d.get("safety_reason"),
                "reasons": d.get("safety_reasons", []),
                "warnings": d.get("safety_warnings", []),
            }
        return {}


_SENSOR_DEFS: tuple[tuple[str, str, Callable[[dict[str, Any]], Any]], ...] = (
    ("automatic_execution_shadow", "DOEMS EMS Automatic Execution Shadow", lambda d: d.get("auto_shadow_status") or "idle"),
    ("automatic_execution_preflight", "DOEMS EMS Automatic Execution Preflight", lambda d: d.get("auto_final_revalidation_status") or d.get("auto_prestart_status") or "idle"),
    ("scheduler_selected_plan", "DOEMS EMS Scheduler Plan", lambda d: f"plan_{d.get('scheduler_selected_slot')}" if d.get("scheduler_selected_slot") is not None else "geen"),
    ("safety_status", "DOEMS EMS Safety Status", lambda d: d.get("safety_status") or "idle"),
    ("controller_status", "DOEMS EMS Controller Status", lambda d: d.get("controller_status") or "idle"),
    ("physical_test_status", "DOEMS EMS Physical Test Status", lambda d: d.get("physical_test_status") or "idle"),
    ("execution_status", "DOEMS EMS Execution Status", lambda d: d.get("execution_status") or "idle"),
    ("execution_audit", "DOEMS EMS Execution Audit", lambda d: d.get("execution_automatic_last_result") or ("running" if d.get("execution_active") and d.get("execution_origin") == "automatic_72h_planner" else "waiting")),
    ("execution_evaluation", "DOEMS EMS Plan vs Actual", lambda d: d.get("execution_automatic_last_result") or "waiting"),
)


class DOEMSAlpha76Sensor(_RuntimeEntity, SensorEntity):
    def __init__(
        self,
        entry: ConfigEntry,
        runtime: DOEMSEMSRuntime,
        key: str,
        name: str,
        value_fn: Callable[[dict[str, Any]], Any],
    ) -> None:
        super().__init__(entry, runtime)
        self.key = key
        self.value_fn = value_fn
        self._attr_name = name
        self._attr_unique_id = f"doems_alpha76_{key}"
        self._attr_suggested_object_id = f"doems_ems_{key}"

    @property
    def native_value(self) -> Any:
        return self.value_fn(self.runtime.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.runtime.data
        if self.key == "automatic_execution_shadow":
            return {
                "technical_ready": d.get("auto_shadow_technical_ready", False),
                "armed": d.get("auto_shadow_armed", False),
                "execution_permitted": d.get("auto_shadow_execution_permitted", False),
                "blockers": d.get("auto_shadow_blockers", []),
                "warnings": d.get("auto_shadow_warnings", []),
                "selected_slot": d.get("auto_shadow_selected_slot"),
                "planner_identity": d.get("auto_shadow_planner_identity"),
                "action": d.get("auto_shadow_action"),
                "purpose": d.get("auto_shadow_purpose"),
            }
        if self.key in {"execution_status", "execution_audit", "execution_evaluation"}:
            return {
                "reason": d.get("execution_reason"),
                "origin": d.get("execution_origin"),
                "slot": d.get("execution_slot"),
                "action": d.get("execution_action"),
                "power_w": d.get("execution_power_w"),
                "target_soc": d.get("execution_target_soc"),
                "planned_energy_kwh": d.get("execution_planned_energy_kwh"),
                "last_result": d.get("execution_last_result"),
                "automatic_last_result": d.get("execution_automatic_last_result"),
                "automatic_run_history": d.get("execution_automatic_run_history", []),
            }
        return {}


def build_alpha76_binary_sensors(
    entry: ConfigEntry, runtime: DOEMSEMSRuntime
) -> list[BinarySensorEntity]:
    return [
        DOEMSAlpha76BinarySensor(entry, runtime, key, name, fn)
        for key, name, fn in _BINARY_DEFS
    ]


def build_alpha76_sensors(
    entry: ConfigEntry, runtime: DOEMSEMSRuntime
) -> list[SensorEntity]:
    return [
        DOEMSAlpha76Sensor(entry, runtime, key, name, fn)
        for key, name, fn in _SENSOR_DEFS
    ]
