"""Read-only Action Bridge runtime and four diagnostic HA entities."""
from __future__ import annotations

from copy import deepcopy
from typing import Callable, Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .planner_action_bridge import build_action_bridge


class ActionBridgeRuntime:
    """Translate notifications from one published Plan72 generation only.

    Translation is bounded by 288 quarters and never calls the expensive planner.
    It is synchronous so no stale bridge worker can publish over a new generation.
    """
    def __init__(self, plan72) -> None:
        self.plan72 = plan72
        self.device = plan72.device
        self.snapshot = build_action_bridge({}, now=dt_util.utcnow())
        self.listeners: list[Callable[[], None]] = []
        self._unsubscribe = None
        self._closed = False

    async def async_setup(self) -> None:
        self._unsubscribe = self.plan72.async_add_listener(self.refresh)
        self.refresh()

    async def async_shutdown(self) -> None:
        self._closed = True
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self.listeners.clear()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self.listeners.append(listener)
        def remove():
            if listener in self.listeners:
                self.listeners.remove(listener)
        return remove

    @callback
    def refresh(self) -> None:
        if self._closed:
            return
        # No awaits and no HA reads: metadata and timeline belong to one snapshot.
        self.snapshot = build_action_bridge(self.plan72.snapshot, now=dt_util.utcnow())
        for listener in tuple(self.listeners):
            listener()


class _BridgeEntity:
    _attr_should_poll = False
    _attr_has_entity_name = False
    _unrecorded_attributes = frozenset({"candidates", "slot_preview", "overflow_candidates"})

    def __init__(self, runtime: ActionBridgeRuntime, suffix: str, label: str) -> None:
        self.runtime = runtime
        self._attr_unique_id = "doems_ems_" + suffix
        self._attr_suggested_object_id = self._attr_unique_id
        self._attr_name = "DOEMS " + label
        self._attr_device_info = runtime.device
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.runtime.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snapshot = self.runtime.snapshot
        attrs = {key: deepcopy(value) for key, value in snapshot.items()
                 if key not in {"candidates", "eligible_candidates", "slot_preview", "overflow_candidates"}}
        if self._attr_unique_id.endswith("action_candidates"):
            attrs["candidates"] = deepcopy(snapshot["candidates"])
        elif self._attr_unique_id.endswith("action_slot_preview"):
            attrs["slot_preview"] = deepcopy(snapshot["slot_preview"])
            attrs["overflow_count"] = len(snapshot["overflow_candidates"])
            attrs["preview_semantics"] = "first_three_eligible_candidates_assuming_free_capacity"
        return attrs


class ActionBridgeSensor(_BridgeEntity, SensorEntity):
    @property
    def native_value(self):
        snapshot = self.runtime.snapshot
        if self._attr_unique_id.endswith("action_bridge_status"):
            return snapshot["status"]
        if self._attr_unique_id.endswith("action_candidates"):
            return snapshot["candidate_count"]
        return len(snapshot["slot_preview"])


class ActionBridgeValid(_BridgeEntity, BinarySensorEntity):
    def __init__(self, runtime):
        super().__init__(runtime, "action_bridge_valid", "Action Bridge Valid")

    @property
    def is_on(self) -> bool:
        return self.runtime.snapshot["valid"] is True


def build_action_bridge_sensors(runtime):
    return [ActionBridgeSensor(runtime, key, label) for key, label in (
        ("action_bridge_status", "Action Bridge Status"),
        ("action_candidates", "Action Candidates"),
        ("action_slot_preview", "Action Slot Preview"),
    )]
