"""Read-only Home Assistant runtime for DOEMS 3.0 Energy Need."""
from __future__ import annotations
from datetime import datetime
from math import sqrt
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENERGY_NEED_ENABLED, CONF_ENERGY_NEED_SOC_ENTITY,
    CONF_ENERGY_NEED_CAPACITY_KWH, CONF_ENERGY_NEED_MIN_SOC_PERCENT,
    CONF_ENERGY_NEED_RESERVE_PERCENT, CONF_ENERGY_NEED_CHARGE_EFFICIENCY,
    CONF_ENERGY_NEED_DISCHARGE_EFFICIENCY, DOMAIN, DEVICE_IDENTIFIER, NAME,
    VERSION,
)
from .const import CONF_ENERGY_NEED_CAPACITY_ENTITY, CONF_ENERGY_NEED_MIN_SOC_ENTITY, CONF_ENERGY_NEED_ROUNDTRIP_EFFICIENCY
from .energy_need import calculate_energy_need


class EnergyNeedRuntime:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: Any, solar: Any):
        self.hass, self.entry = hass, entry
        self.coordinator, self.solar = coordinator, solar
        self.listeners: list[Any] = []
        self.unsubs: list[Any] = []
        self.snapshot: dict[str, Any] = {"status": "waiting_for_complete_forecast", "valid": False, "reason": "initializing"}
        self.device = DeviceInfo(identifiers={(DOMAIN, DEVICE_IDENTIFIER)}, name=NAME, manufacturer=NAME, model="Energy Management System", sw_version=VERSION)

    async def async_setup(self) -> None:
        self.unsubs.append(self.coordinator.async_add_listener(self.refresh))
        self.unsubs.append(self.solar.async_add_listener(self.refresh))
        self.unsubs.append(async_track_state_change_event(self.hass, [self.entry.options[key] for key in (CONF_ENERGY_NEED_SOC_ENTITY, CONF_ENERGY_NEED_CAPACITY_ENTITY, CONF_ENERGY_NEED_MIN_SOC_ENTITY)], self._soc_changed))
        self.unsubs.append(async_track_time_change(self.hass, self._quarter_tick, minute=[0, 15, 30, 45], second=2))
        self.refresh()

    async def async_shutdown(self) -> None:
        for unsubscribe in self.unsubs:
            unsubscribe()
        self.unsubs.clear()

    def async_add_listener(self, callback_fn: Any) -> Any:
        self.listeners.append(callback_fn)
        @callback
        def unsub() -> None:
            if callback_fn in self.listeners:
                self.listeners.remove(callback_fn)
        return unsub

    @callback
    def _soc_changed(self, _event: Any) -> None:
        self.refresh()

    async def _quarter_tick(self, _now: datetime) -> None:
        self.refresh()

    @callback
    def refresh(self) -> None:
        opts = self.entry.options
        state = self.hass.states.get(opts.get(CONF_ENERGY_NEED_SOC_ENTITY))
        soc = state.state if state is not None else None
        capacity_state = self.hass.states.get(opts.get(CONF_ENERGY_NEED_CAPACITY_ENTITY))
        minimum_state = self.hass.states.get(opts.get(CONF_ENERGY_NEED_MIN_SOC_ENTITY))
        roundtrip = opts.get(CONF_ENERGY_NEED_ROUNDTRIP_EFFICIENCY)
        try:
            symmetric_efficiency = sqrt(float(roundtrip) / 100)
        except (ValueError, TypeError):
            symmetric_efficiency = None
        now = dt_util.utcnow()
        # Both managers expose native quarter data directly, without history/recorder reads.
        home = self.coordinator.forecast(now=now)
        solar = self.solar.points
        if self.solar.source_status != "ok":
            self.snapshot = {"status": "waiting_for_complete_forecast", "valid": False, "reason": "solar_source_" + self.solar.source_status}
            for listener in tuple(self.listeners):
                listener()
            return
        self.snapshot = calculate_energy_need(
            [{"start": slot.start, "energy_kwh": slot.energy_kwh} for slot in home],
            [{"start": slot.start, "energy_kwh": slot.total_kwh} for slot in solar],
            now=now, soc_percent=soc,
            capacity_kwh=capacity_state.state if capacity_state is not None else None,
            min_soc_percent=minimum_state.state if minimum_state is not None else None,
            reserve_percent=opts[CONF_ENERGY_NEED_RESERVE_PERCENT],
            charge_efficiency=symmetric_efficiency,
            discharge_efficiency=symmetric_efficiency,
        )
        for listener in tuple(self.listeners):
            listener()


FIELDS = (
    ("energy_need_status", "Energy Need Status", "status", None),
    ("energy_need_reason", "Energy Need Reason", "reason", None),
    ("energy_need_to_solar", "Energy Need To Solar", "to_solar_kwh", "kWh"),
    ("next_usable_solar", "Next Usable Solar", "next_usable_solar", None),
    ("available_battery_energy", "Available Battery Energy", "available_battery_energy_kwh", "kWh"),
    ("safety_reserve", "Safety Reserve", "safety_reserve_kwh", "kWh"),
    ("required_energy", "Required Energy", "required_energy_kwh", "kWh"),
    ("grid_charge_need", "Grid Charge Need", "grid_charge_need_kwh", "kWh"),
    ("tradable_battery_energy", "Tradable Battery Energy", "tradable_battery_energy_kwh", "kWh"),
    ("energy_need_horizon", "Energy Need Horizon", "horizon_hours", "h"),
)


class EnergyNeedSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, runtime: EnergyNeedRuntime, field: tuple):
        self.runtime, self.field = runtime, field
        suffix, label, key, unit = field
        self._attr_name = "DOEMS EMS " + label
        self._attr_unique_id = "doems_ems_" + suffix
        self._attr_suggested_object_id = "doems_ems_" + suffix
        self._attr_device_info = runtime.device
        if unit:
            self._attr_native_unit_of_measurement = unit
        if unit == "kWh":
            self._attr_device_class = SensorDeviceClass.ENERGY
        self.remove_listener = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.remove_listener = self.runtime.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        if self.remove_listener:
            self.remove_listener()
        await super().async_will_remove_from_hass()

    @property
    def native_value(self) -> Any:
        return self.runtime.snapshot.get(self.field[2])


class EnergyNeedValid(BinarySensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS EMS Energy Need Valid"
    _attr_unique_id = "doems_ems_energy_need_valid"
    _attr_suggested_object_id = "doems_ems_energy_need_valid"

    def __init__(self, runtime: EnergyNeedRuntime):
        self.runtime = runtime
        self._attr_device_info = runtime.device
        self.remove_listener = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.remove_listener = self.runtime.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        if self.remove_listener:
            self.remove_listener()
        await super().async_will_remove_from_hass()

    @property
    def is_on(self) -> bool:
        return bool(self.runtime.snapshot.get("valid"))
