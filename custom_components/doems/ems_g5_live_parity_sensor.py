"""Public Step 13 G5 frozen-live parity result sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_INSTANCE_NAME,
    DEFAULT_INSTANCE_NAME,
    DEVICE_IDENTIFIER,
    DOMAIN,
    NAME,
    VERSION,
)
from .ems_g5_live_parity_runtime import DOEMSG5LiveParityRuntime


class DOEMSG5LiveParitySensor(SensorEntity):
    """Compact public state for the persistent G5 evidence."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS G5 Frozen Live Parity"
    _attr_unique_id = "doems_g5_frozen_live_parity"
    _attr_suggested_object_id = "doems_g5_frozen_live_parity"
    _attr_icon = "mdi:compare-horizontal"
    _unrecorded_attributes = frozenset(
        {"differences", "golden_decision", "doems_decision"}
    )

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: DOEMSG5LiveParityRuntime,
    ) -> None:
        self.runtime = runtime
        self._remove_listener = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
            name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
            manufacturer=NAME,
            model="Energy Management System",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.runtime.add_listener(self._handle_update)
        await self.runtime.async_ensure_loaded()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return self.runtime.state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.runtime.attributes()
