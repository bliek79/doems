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
from .ems_runtime import DOEMSEMSRuntime
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
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    entities: list[SwitchEntity] = []
    presence = entry_data.get("presence")
    if isinstance(presence, DOEMSPresenceStore):
        entities.append(DOEMSAwayScheduleEnabledSwitch(entry, presence))
    runtime = entry_data.get("ems_runtime")
    if isinstance(runtime, DOEMSEMSRuntime):
        entities.append(DOEMSAutomaticExecutionSwitch(entry, runtime))
    if entities:
        async_add_entities(entities)


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


class DOEMSAutomaticExecutionSwitch(SwitchEntity):
    """Explicit fail-safe Step 12.4 arm for future automatic execution.

    This switch only changes the permission bit consumed by the read-only
    Automatic Execution Gate. Step 12.4 never invokes the Execution Controller.
    The state is intentionally not restored after integration reload/restart.
    """

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS Automatic Execution"
    _attr_unique_id = "doems_automatic_execution"
    _attr_suggested_object_id = "doems_automatic_execution"
    _attr_icon = "mdi:robot-off-outline"

    def __init__(self, entry: ConfigEntry, runtime: DOEMSEMSRuntime) -> None:
        self.runtime = runtime
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        return self.runtime.automatic_execution_armed

    async def async_turn_on(self, **kwargs) -> None:
        await self.runtime.async_set_automatic_execution_armed(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.runtime.async_set_automatic_execution_armed(False)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        data = self.runtime.snapshot()
        return {
            "mode": "guarded_handoff",
            "technical_ready": data.get("auto_execution_gate_technical_ready", False),
            "gate_status": data.get("auto_execution_gate_status"),
            "blockers": data.get("auto_execution_gate_blockers", []),
            "warnings": data.get("auto_execution_gate_warnings", []),
            "execution_permitted": data.get(
                "auto_execution_gate_execution_permitted", False
            ),
            "physical_execution_enabled": False,
            "execution_controller_invoked": False,
            "service_calls_performed": False,
            "physical_execution_authority": False,
            "restart_policy": "fail_safe_off",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.runtime.async_add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
