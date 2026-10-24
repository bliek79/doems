"""Read-only Home Assistant runtime for the DOEMS battery input contract."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .battery_contract_model import evaluate_battery_input_contract
from .const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_CHARGE_POWER_ENTITY,
    CONF_BATTERY_DISCHARGE_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_STATUS_ENTITY,
)

_ROLE_TO_OPTION = {
    "soc": CONF_BATTERY_SOC_ENTITY,
    "capacity": CONF_BATTERY_CAPACITY_ENTITY,
    "charge_power": CONF_BATTERY_CHARGE_POWER_ENTITY,
    "discharge_power": CONF_BATTERY_DISCHARGE_POWER_ENTITY,
    "device_status": CONF_BATTERY_STATUS_ENTITY,
}


class DOEMSBatteryInputContract:
    """Observe configured battery sources without any actuation."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._remove_source_listener: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []

    @property
    def source_entities(self) -> list[str]:
        return list(
            dict.fromkeys(
                str(self.entry.options.get(option) or "")
                for option in _ROLE_TO_OPTION.values()
                if self.entry.options.get(option)
            )
        )

    async def async_setup(self) -> None:
        if self.source_entities:
            self._remove_source_listener = async_track_state_change_event(
                self.hass,
                self.source_entities,
                self._handle_source_update,
            )

    async def async_shutdown(self) -> None:
        if self._remove_source_listener is not None:
            self._remove_source_listener()
            self._remove_source_listener = None
        self._listeners.clear()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @callback
    def _handle_source_update(self, event: Event[EventStateChangedData]) -> None:
        for listener in tuple(self._listeners):
            listener()

    def snapshot(self) -> dict[str, object]:
        sources: dict[str, dict[str, object]] = {}
        for role, option in _ROLE_TO_OPTION.items():
            entity_id = self.entry.options.get(option)
            state = self.hass.states.get(entity_id) if entity_id else None
            sources[role] = {
                "entity_id": entity_id,
                "state": state.state if state is not None else None,
                "unit": state.attributes.get("unit_of_measurement") if state is not None else None,
            }
        return evaluate_battery_input_contract(sources)
