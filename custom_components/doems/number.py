"""Number entities for definitive DOEMS EMS plans."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_EMS_ENABLED,
    CONF_INSTANCE_NAME,
    DEFAULT_INSTANCE_NAME,
    DEVICE_IDENTIFIER,
    DOMAIN,
    NAME,
    PLAN_SLOT_COUNT,
    VERSION,
)
from .ems_runtime import DOEMSEMSRuntime


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
        name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
        manufacturer=NAME,
        model="Energy Management System",
        sw_version=VERSION,
    )


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
    PlanNumberDefinition("target_soc", "target_soc", "Target SOC", 0, 100, 1, PERCENTAGE),
    PlanNumberDefinition("max_runtime_h", "max_runtime", "Maximum Runtime", 0.25, 12, 0.25, UnitOfTime.HOURS),
    PlanNumberDefinition("max_start_delay_min", "max_start_delay", "Maximum Start Delay", 1, 120, 1, UnitOfTime.MINUTES),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if not entry.options.get(CONF_EMS_ENABLED, False):
        return
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("ems_runtime")
    if not isinstance(runtime, DOEMSEMSRuntime):
        return
    async_add_entities(
        DOEMSPlanNumber(entry, runtime, slot, definition)
        for slot in range(1, PLAN_SLOT_COUNT + 1)
        for definition in DEFINITIONS
    )


class DOEMSPlanNumber(NumberEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: DOEMSEMSRuntime,
        slot: int,
        definition: PlanNumberDefinition,
    ) -> None:
        self.runtime = runtime
        self.plan_store = runtime.plan_store
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
        self.async_on_remove(self.plan_store.add_listener(self.async_write_ha_state))

    @property
    def native_min_value(self) -> float:
        if self.definition.field == "target_soc":
            return float(self.runtime.settings.technical_min_soc_percent)
        return float(self._attr_native_min_value)

    @property
    def native_max_value(self) -> float:
        if self.definition.field == "target_soc":
            return float(self.runtime.settings.max_soc_percent)
        if self.definition.field == "power_w":
            action = self.plan_store.get_value(self.slot, "action")
            if action == "ontladen":
                return float(self.runtime.settings.max_discharge_power_w)
            return float(self.runtime.settings.max_charge_power_w)
        return float(self._attr_native_max_value)

    @property
    def native_value(self) -> float:
        return float(self.plan_store.get_value(self.slot, self.definition.field))

    async def async_set_native_value(self, value: float) -> None:
        value = max(self.native_min_value, min(self.native_max_value, float(value)))
        steps = round((value - self.native_min_value) / self.native_step)
        value = self.native_min_value + steps * self.native_step
        await self.plan_store.async_set_value(self.slot, self.definition.field, value)
