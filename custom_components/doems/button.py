"""Non-actuating emergency acknowledgement button for DOEMS."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME, DEVICE_IDENTIFIER, DOMAIN, NAME, VERSION,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]["combined_execution_shadow"]
    async_add_entities([DOEMSEmergencyAcknowledgeButton(hass, entry, runtime)])


class DOEMSEmergencyAcknowledgeButton(ButtonEntity):
    _attr_name = "DOEMS Emergency Stop Acknowledge"
    _attr_unique_id = "doems_ems_emergency_acknowledge"
    _attr_suggested_object_id = "doems_ems_emergency_acknowledge"
    _attr_icon = "mdi:shield-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime) -> None:
        self.hass = hass
        self.runtime = runtime
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
            name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
            manufacturer=NAME,
            model="Energy Management System",
            sw_version=VERSION,
        )

    async def async_press(self) -> None:
        # Central service exclusively validates live safety state. A button
        # press supplies no booleans, overrides or physical battery commands.
        await self.hass.services.async_call(
            DOMAIN, "reset_emergency_status", {}, blocking=True
        )
