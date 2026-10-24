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
from .energy_coordinator import DOEMSEnergyCoordinator
from .manual_plan_model import PLAN_SLOT_COUNT
from .manual_plan_store import DOEMSManualPlanStore


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DOEMS selects for forecast and manual Plan Store."""
    entities: list[SelectEntity] = []
    coordinator = entry.runtime_data
    if isinstance(coordinator, DOEMSEnergyCoordinator):
        entities.append(DOEMSEnergyProfileSelect(entry, coordinator))

    store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("manual_plan_store")
    if isinstance(store, DOEMSManualPlanStore):
        for slot in range(1, PLAN_SLOT_COUNT + 1):
            entities.extend(
                [
                    DOEMSManualPlanSelect(
                        entry,
                        store,
                        slot,
                        "action",
                        "Action",
                        ["geen", "laden", "ontladen"],
                    ),
                    DOEMSManualPlanSelect(
                        entry,
                        store,
                        slot,
                        "execution_mode",
                        "Execution Mode",
                        ["direct", "gepland"],
                    ),
                ]
            )

    if entities:
        async_add_entities(entities)


class DOEMSEnergyProfileSelect(SelectEntity):
    """Select the active learning profile without mixing incompatible quarters."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS Energy Profile"
    _attr_unique_id = "doems_energy_profile"
    _attr_suggested_object_id = "doems_energy_profile"
    _attr_options = [PROFILE_NORMAL, PROFILE_AWAY]
    _attr_icon = "mdi:home-account"

    def __init__(self, entry: ConfigEntry, coordinator: DOEMSEnergyCoordinator) -> None:
        self.entry = entry
        self.coordinator = coordinator
        self._remove_listener = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
            name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
            manufacturer=NAME,
            model="Energy Management System",
            sw_version=VERSION,
        )

    @property
    def current_option(self) -> str:
        return self.coordinator.profile

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "learning_enabled": True,
            "forecast_enabled": True,
            "previous_profile": self.coordinator.previous_profile,
            "profile_changed_at": self.coordinator.profile_changed_at,
            "profile_change_source": self.coordinator.profile_change_source,
        }

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unsupported profile: {option}")
        await self.coordinator.async_set_profile(option, source="manual_select")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.coordinator.async_add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()



class DOEMSManualPlanSelect(SelectEntity):
    """Editable select field for one manual Plan Store slot."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(
        self,
        entry: ConfigEntry,
        store: DOEMSManualPlanStore,
        slot: int,
        field: str,
        label: str,
        options: list[str],
    ) -> None:
        self.store = store
        self.slot = slot
        self.field = field
        self._attr_name = f"DOEMS Plan {slot} {label}"
        self._attr_unique_id = f"doems_plan_{slot}_{field}"
        self._attr_suggested_object_id = f"doems_plan_{slot}_{field}"
        self._attr_options = options
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
            name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
            manufacturer=NAME,
            model="Energy Management System",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.store.add_listener(self.async_write_ha_state))

    @property
    def current_option(self) -> str | None:
        value = self.store.get_value(self.slot, self.field)
        return str(value) if value in self.options else None

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unsupported option: {option}")
        await self.store.async_set_value(self.slot, self.field, option)
