"""The four approved chapter-8 diagnostic entities; no control entities."""
from copy import deepcopy

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (DOMAIN, DEVICE_IDENTIFIER, CONF_INSTANCE_NAME,
                    DEFAULT_INSTANCE_NAME, NAME, VERSION)

ENTITY_FIELDS = ("status", "selected_plan", "reason", "ready")


class _SchedulerEntity:
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({"scheduler_slots", "evaluated_at", "next_evaluation_at"})

    def __init__(self, entry, runtime, field):
        self.runtime, self.field = runtime, field
        self._attr_unique_id = f"{entry.entry_id}_scheduler_{field}"
        self._attr_suggested_object_id = f"doems_scheduler_{field}"
        self._attr_name = "DOEMS Scheduler " + field.replace("_", " ")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
            name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
            manufacturer=NAME, model="Energy Management System", sw_version=VERSION)
        self._remove_listener = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = self.runtime.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    @property
    def extra_state_attributes(self):
        # All four read one atomic runtime snapshot; entities do not evaluate.
        return deepcopy(self.runtime.snapshot)


class SchedulerSensor(_SchedulerEntity, SensorEntity):
    @property
    def native_value(self):
        snapshot = self.runtime.snapshot
        if self.field == "selected_plan":
            slot = snapshot.get("scheduler_selected_slot")
            return f"slot_{slot}" if slot is not None else "geen"
        return snapshot.get("scheduler_" + self.field)


class SchedulerReady(_SchedulerEntity, BinarySensorEntity):
    def __init__(self, entry, runtime):
        super().__init__(entry, runtime, "ready")

    @property
    def is_on(self):
        return self.runtime.snapshot.get("scheduler_ready", False)


def build_scheduler_sensors(entry, runtime):
    return [SchedulerSensor(entry, runtime, field) for field in ENTITY_FIELDS[:-1]]
