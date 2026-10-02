"""Switch entities for DOEMS."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

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


class DOEMSAutomaticExecutionSwitch(RestoreEntity, SwitchEntity):
    """Frozen Alpha76 arm switch for automatic physical execution only."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS Automatic Execution"
    _attr_unique_id = "doems_automatic_execution"
    _attr_suggested_object_id = "doems_automatic_execution"
    _attr_icon = "mdi:robot"

    def __init__(self, entry: ConfigEntry, runtime: DOEMSEMSRuntime) -> None:
        self.runtime = runtime
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        return self.runtime.automatic_execution_armed

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        # Exact Alpha76 migration/restore rule: only a previously saved
        # live_guarded ON state may restore the automatic physical arm.
        armed = bool(
            previous is not None
            and previous.state == "on"
            and previous.attributes.get("mode") == "live_guarded"
        )
        await self.runtime.async_set_automatic_execution_armed(armed)
        self._remove_listener = self.runtime.async_add_listener(self._handle_update)

    async def async_turn_on(self, **kwargs) -> None:
        await self.runtime.async_set_automatic_execution_armed(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.runtime.async_set_automatic_execution_armed(False)
        execution = self.runtime.execution.data
        if (
            execution.get("active")
            and execution.get("origin") == "automatic_72h_planner"
        ):
            await self.runtime.execution.async_stop(
                "automatic_execution_disarmed", emergency=False
            )
        elif execution.get("auto_mode_switch_active"):
            await self.runtime.execution.async_abort_automatic_arming(
                "automatic_execution_disarmed"
            )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        data = self.runtime.data
        return {
            "mode": "live_guarded",
            "technical_ready": data.get("auto_shadow_technical_ready", False),
            "execution_status": data.get("auto_shadow_status"),
            "blockers": data.get("auto_shadow_blockers", []),
            "warnings": data.get("auto_shadow_warnings", []),
            "physical_execution_enabled": True,
            "execution_permitted": data.get(
                "auto_shadow_execution_permitted", False
            ),
        }

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

