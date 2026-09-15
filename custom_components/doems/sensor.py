"""Foundation entities for DOEMS."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_INSTANCE_NAME,
    DEFAULT_INSTANCE_NAME,
    DEVICE_IDENTIFIER,
    DOMAIN,
    FOUNDATION_PHASE,
    NAME,
    VERSION,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up foundation sensors."""
    async_add_entities([DOEMSFoundationStatusSensor(entry)])


class DOEMSFoundationStatusSensor(SensorEntity):
    """Expose the clean DOEMS foundation status."""

    _attr_has_entity_name = True
    _attr_name = "Status"
    _attr_icon = "mdi:home-lightning-bolt-outline"
    _attr_native_value = "ready"
    _attr_unique_id = "foundation_status"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the foundation status sensor."""
        instance_name = entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
            name=instance_name,
            manufacturer=NAME,
            model="Energy Management System",
            sw_version=VERSION,
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return identity and safety attributes."""
        return {
            "phase": FOUNDATION_PHASE,
            "domain": DOMAIN,
            "version": VERSION,
            "storage_namespace": DOMAIN,
            "installation_required_input_count": 0,
            "forecast_enabled": False,
            "ems_enabled": False,
            "physical_execution_authority": False,
            "identity_pure": True,
        }
