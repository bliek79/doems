"""Non-actuating emergency acknowledgement button for DOEMS."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]["combined_execution_shadow"]
    async_add_entities([DOEMSEmergencyAcknowledgeButton(hass, runtime)])


class DOEMSEmergencyAcknowledgeButton(ButtonEntity):
    _attr_name = "DOEMS EMS noodstop bevestigen"
    _attr_unique_id = "doems_ems_emergency_acknowledge"
    _attr_suggested_object_id = "doems_ems_emergency_acknowledge"
    _attr_icon = "mdi:shield-check"

    def __init__(self, hass: HomeAssistant, runtime) -> None:
        self.hass = hass
        self.runtime = runtime

    async def async_press(self) -> None:
        # Central service exclusively validates live safety state. A button
        # press supplies no booleans, overrides or physical battery commands.
        await self.hass.services.async_call(
            DOMAIN, "reset_emergency_status", {}, blocking=True
        )
