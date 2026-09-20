"""Switch entities for DOEMS."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
        async_add_entities([DOEMSAwayScheduleEnabledSwitch(entry, presence)])


class DOEMSAwayScheduleEnabledSwitch(SwitchEntity):
    """Enable or disable the runtime Away schedule."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS Away Schedule Enabled"
    _attr_unique_id = "doems_away_schedule_enabled"
    _attr_suggested_object_id = "doems_away_schedule_enabled"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: ConfigEntry, presence: DOEMSPresenceStore) -> None:
        self.presence = presence
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        return self.presence.schedule_enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.presence.async_set_schedule_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.presence.async_set_schedule_enabled(False)

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
