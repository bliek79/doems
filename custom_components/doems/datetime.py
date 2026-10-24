"""Manual Plan Store datetime entities for DOEMS R2."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_INSTANCE_NAME,
    DEFAULT_INSTANCE_NAME,
    DEVICE_IDENTIFIER,
    DOMAIN,
    NAME,
    VERSION,
)
from .manual_plan_model import PLAN_SLOT_COUNT
from .manual_plan_store import DOEMSManualPlanStore


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
        name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
        manufacturer=NAME,
        model="Energy Management System",
        sw_version=VERSION,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("manual_plan_store")
    if not isinstance(store, DOEMSManualPlanStore):
        return
    async_add_entities(
        DOEMSManualPlanStartTime(entry, store, slot)
        for slot in range(1, PLAN_SLOT_COUNT + 1)
    )


class DOEMSManualPlanStartTime(DateTimeEntity):
    """Start time for one manual Plan Store slot."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, entry: ConfigEntry, store: DOEMSManualPlanStore, slot: int) -> None:
        self.store = store
        self.slot = slot
        self._attr_name = f"DOEMS Plan {slot} Start Time"
        self._attr_unique_id = f"doems_plan_{slot}_start_time"
        self._attr_suggested_object_id = f"doems_plan_{slot}_start_time"
        self._attr_icon = "mdi:calendar-clock"
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.store.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> datetime | None:
        value = self.store.get_value(self.slot, "start_time")
        if not value:
            return None
        parsed = dt_util.parse_datetime(str(value))
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return parsed

    async def async_set_value(self, value: datetime) -> None:
        await self.store.async_set_value(self.slot, "start_time", value)
