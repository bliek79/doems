"""Select entities for DOEMS."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
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
    PROFILE_AWAY,
    PROFILE_NORMAL,
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
    """Set up the shared DOEMS presence profile select."""
    presence = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("presence")
    if isinstance(presence, DOEMSPresenceStore):
        async_add_entities([DOEMSPresenceProfileSelect(entry, presence)])


class DOEMSPresenceProfileSelect(SelectEntity):
    """Manual normal/Away profile control backed by the PresenceStore."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS Presence Profile"
    _attr_unique_id = "doems_presence_profile"
    _attr_suggested_object_id = "doems_presence_profile"
    _attr_options = [PROFILE_NORMAL, PROFILE_AWAY]
    _attr_icon = "mdi:home-account"

    def __init__(self, entry: ConfigEntry, presence: DOEMSPresenceStore) -> None:
        self.presence = presence
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

    @property
    def current_option(self) -> str | None:
        return self.presence.manual_profile if self.presence.manual_profile in self.options else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "effective_profile": self.presence.effective_profile,
            "profile_source": self.presence.profile_source,
            "previous_profile": self.presence.previous_profile,
            "profile_changed_at": self.presence.profile_changed_at,
            "manual_override_active": self.presence.manual_override_active,
            "schedule_active": self.presence.schedule_active,
        }

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unsupported profile: {option}")
        await self.presence.async_set_manual_profile(option)

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
