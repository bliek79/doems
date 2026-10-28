"""Default-off master gate for DOEMS physical execution."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME, DEVICE_IDENTIFIER, DOMAIN, NAME, VERSION,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]["combined_execution_shadow"]
    registry = er.async_get(hass)
    old_entity_id = registry.async_get_entity_id("switch", DOMAIN, "doems_ems_master_execution")
    new_entity_id = "switch.doems_automatic_execution"
    if old_entity_id and old_entity_id != new_entity_id and not registry.async_get(new_entity_id):
        registry.async_update_entity(old_entity_id, new_entity_id=new_entity_id)
    async_add_entities([DOEMSMasterExecutionSwitch(entry, runtime)])


class DOEMSMasterExecutionSwitch(SwitchEntity):
    _attr_name = "DOEMS Automatic Execution"
    _attr_unique_id = "doems_ems_master_execution"
    _attr_suggested_object_id = "doems_automatic_execution"
    _attr_icon = "mdi:shield-lock"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, runtime) -> None:
        self.runtime = runtime
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
            name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
            manufacturer=NAME,
            model="Energy Management System",
            sw_version=VERSION,
        )

    @property
    def is_on(self) -> bool:
        return self.runtime.master_enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.runtime.async_set_master_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.runtime.async_set_master_enabled(False)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.runtime.async_add_listener(self.async_write_ha_state))
