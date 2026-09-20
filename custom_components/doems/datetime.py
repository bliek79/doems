"""Date/time entities for DOEMS Away scheduling."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_INSTANCE_NAME,
    DEFAULT_INSTANCE_NAME,
    DEVICE_IDENTIFIER,
    DOMAIN,
    NAME,
    VERSION,
)
from .presence import DOEMSPresenceStore


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
    presence = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("presence")
    if isinstance(presence, DOEMSPresenceStore):
        async_add_entities(
            [
                DOEMSAwayDateTime(entry, presence, "start"),
                DOEMSAwayDateTime(entry, presence, "end"),
            ]
        )


class DOEMSAwayDateTime(DateTimeEntity):
    """Runtime Away start/end boundary."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(
        self,
        entry: ConfigEntry,
        presence: DOEMSPresenceStore,
        boundary: str,
    ) -> None:
        self.presence = presence
        self.boundary = boundary
        self._remove_listener = None
        is_start = boundary == "start"
        self._attr_name = "DOEMS Away Start" if is_start else "DOEMS Away End"
        self._attr_unique_id = "doems_away_start" if is_start else "doems_away_end"
        self._attr_suggested_object_id = "doems_away_start" if is_start else "doems_away_end"
        self._attr_icon = "mdi:calendar-start" if is_start else "mdi:calendar-end"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> datetime | None:
        return self.presence.away_start if self.boundary == "start" else self.presence.away_end

    async def async_set_value(self, value: datetime) -> None:
        if self.boundary == "start":
            await self.presence.async_set_away_start(value)
        else:
            await self.presence.async_set_away_end(value)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.presence.async_add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
