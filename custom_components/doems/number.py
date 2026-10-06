"""Manual Plan Store number entities for DOEMS R2."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
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
from .manual_plan_model import PLAN_SLOT_COUNT
from .manual_plan_store import DOEMSManualPlanStore


@dataclass(frozen=True)
class PlanNumberDefinition:
    field: str
    object_suffix: str
    label: str
    minimum: float
    maximum: float
    step: float
    unit: str | None = None


DEFINITIONS = (
    PlanNumberDefinition("power_w", "power", "Power", 100, 3500, 100, UnitOfPower.WATT),
    PlanNumberDefinition("target_soc", "target_soc", "Target SOC", 5, 100, 1, PERCENTAGE),
    PlanNumberDefinition("max_runtime_h", "max_runtime", "Maximum Runtime", 0.5, 12, 0.5, UnitOfTime.HOURS),
    PlanNumberDefinition("max_start_delay_min", "max_start_delay", "Maximum Start Delay", 1, 120, 1, UnitOfTime.MINUTES),
)


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
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("manual_plan_store")
    if not isinstance(store, DOEMSManualPlanStore):
        return
    async_add_entities(
        DOEMSManualPlanNumber(entry, store, slot, definition)
        for slot in range(1, PLAN_SLOT_COUNT + 1)
        for definition in DEFINITIONS
    )


class DOEMSManualPlanNumber(NumberEntity):
    """Editable number field for one manual Plan Store slot."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        entry: ConfigEntry,
        store: DOEMSManualPlanStore,
        slot: int,
        definition: PlanNumberDefinition,
    ) -> None:
        self.store = store
        self.slot = slot
        self.definition = definition
        self._attr_name = f"DOEMS Plan {slot} {definition.label}"
        self._attr_unique_id = f"doems_plan_{slot}_{definition.object_suffix}"
        self._attr_suggested_object_id = f"doems_plan_{slot}_{definition.object_suffix}"
        self._attr_native_min_value = definition.minimum
        self._attr_native_max_value = definition.maximum
        self._attr_native_step = definition.step
        self._attr_native_unit_of_measurement = definition.unit
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.store.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> float:
        return float(self.store.get_value(self.slot, self.definition.field))

    async def async_set_native_value(self, value: float) -> None:
        value = max(self.native_min_value, min(self.native_max_value, float(value)))
        steps = round((value - self.native_min_value) / self.native_step)
        value = self.native_min_value + steps * self.native_step
        await self.store.async_set_value(self.slot, self.definition.field, value)
