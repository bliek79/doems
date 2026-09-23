"""Step 13 G5 diagnostic button for DOEMS."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
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
from .ems_g5_live_parity_runtime import get_g5_live_parity_runtime
from .ems_runtime import DOEMSEMSRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Expose the G5 capture button only when EMS is enabled."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    ems_runtime = entry_data.get("ems_runtime")
    if not isinstance(ems_runtime, DOEMSEMSRuntime):
        return
    async_add_entities(
        [
            DOEMSG5FrozenLiveParityCaptureButton(
                entry,
                get_g5_live_parity_runtime(ems_runtime),
            )
        ]
    )


class DOEMSG5FrozenLiveParityCaptureButton(ButtonEntity):
    """Capture one live EMS snapshot and run the pure G5 comparator."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS G5 Capture Frozen Live Parity"
    _attr_unique_id = "doems_g5_capture_frozen_live_parity"
    _attr_suggested_object_id = "doems_g5_capture_frozen_live_parity"
    _attr_icon = "mdi:camera-lock-outline"

    def __init__(self, entry: ConfigEntry, runtime) -> None:
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
    def extra_state_attributes(self) -> dict[str, object]:
        attrs = self.runtime.attributes()
        attrs["status"] = self.runtime.state()
        attrs["capture_scope"] = "one_frozen_live_input_two_pure_decision_paths"
        attrs["execution_controller_called"] = False
        return attrs

    async def async_press(self) -> None:
        try:
            await self.runtime.async_capture_and_compare()
        except RuntimeError as err:
            raise HomeAssistantError(str(err)) from err
