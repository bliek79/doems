"""Config and options flow for DOEMS."""
from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_CHARGE_POWER_ENTITY, CONF_BATTERY_DISCHARGE_POWER_ENTITY, CONF_BATTERY_PRESENT,
    CONF_ENERGY_FORECAST_ENABLED, CONF_ENERGY_SOURCE_MODE, CONF_ENERGY_START_PROFILE,
    CONF_GRID_NET_POWER_ENTITY, CONF_GRID_SIGN_CONVENTION, CONF_HOME_POWER_ENTITY, CONF_INSTANCE_NAME,
    CONF_SOLAR_ARRAY_COUNT, CONF_SOLAR_ARRAYS, CONF_SOLAR_FOUNDATION_ENABLED, CONF_SOLAR_INVERTER_GROUP_COUNT,
    CONF_SOLAR_INVERTER_GROUPS, CONF_SOLAR_LATITUDE, CONF_SOLAR_LOCATION_SOURCE, CONF_SOLAR_LONGITUDE,
    CONF_SOLAR_POWER_ENTITY, CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY,
    CONF_PRICES_ENABLED, CONF_PRICE_RESOLUTION_PREFERENCE, CONF_TARIFF_PROFILE_ID, CONF_TARIFF_SUPPLIER,
    CONF_TARIFF_VALID_FROM, CONF_VAT_PERCENT, CONF_ELECTRICITY_IMPORT_SUPPLIER, CONF_ELECTRICITY_IMPORT_TAX,
    CONF_ELECTRICITY_EXPORT_SUPPLIER, CONF_ELECTRICITY_EXPORT_TAX, CONF_ELECTRICITY_FIXED_SUPPLY_PER_DAY,
    CONF_ELECTRICITY_GRID_PER_DAY, CONF_ELECTRICITY_TAX_CREDIT_PER_DAY, CONF_GAS_PRICES_ENABLED,
    CONF_GAS_MARKET_ENTITY, CONF_GAS_SUPPLIER, CONF_GAS_TAX, CONF_GAS_FIXED_SUPPLY_PER_DAY, CONF_GAS_GRID_PER_DAY,
    DEFAULT_INSTANCE_NAME, DOMAIN, ENERGY_SOURCE_BALANCE, ENERGY_SOURCE_DIRECT, GRID_SIGN_POSITIVE_EXPORT,
    GRID_SIGN_POSITIVE_IMPORT, NAME, PROFILE_AWAY, PROFILE_NORMAL, SOLAR_LOCATION_HOME_ASSISTANT,
    SOLAR_LOCATION_OVERRIDE, SOLAR_MAX_ARRAYS, SOLAR_MAX_INVERTER_GROUPS,
    PRICE_RESOLUTION_AUTO, PRICE_RESOLUTION_15_MIN, PRICE_RESOLUTION_60_MIN,
)
from .energy_sources import normalize_power_w
from .solar_foundation_model import validate_solar_foundation


def _power_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))

def _sensor_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))

def _select(options: list[tuple[str, str]]) -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(
        options=[selector.SelectOptionDict(value=value, label=label) for value, label in options],
        mode=selector.SelectSelectorMode.DROPDOWN,
    ))

def _number(minimum: float, maximum: float, step: float, unit: str | None = None) -> selector.NumberSelector:
    """Build a numeric selector without serializing a null unit."""
    config: selector.NumberSelectorConfig = {
        "min": minimum, "max": maximum, "step": step, "mode": selector.NumberSelectorMode.BOX,
    }
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)

def _required_entity(key: str, current: str | None) -> vol.Marker:
    return vol.Required(key, default=current) if current else vol.Required(key)

def _optional_entity(key: str, current: str | None) -> vol.Marker:
    return vol.Optional(key, default=current) if current else vol.Optional(key)

def _validate_power_entity(hass: HomeAssistant, entity_id: str | None, *, allow_negative: bool) -> str | None:
    if not entity_id:
        return "source_required"
    object_id = entity_id.split(".", 1)[1] if "." in entity_id else entity_id
    if object_id.startswith("doems_"):
        return "doems_source_not_allowed"
    state = hass.states.get(entity_id)
    if state is None:
        return "source_not_found"
    unit = state.attributes.get("unit_of_measurement")
    if unit not in {"W", "kW"}:
        return "unsupported_unit"
    value = normalize_power_w(state.state, unit, allow_negative=True)
    if value is not None and not allow_negative and value < 0:
        return "negative_value_not_allowed"
    return None

def _validate_generic_sensor(hass: HomeAssistant, entity_id: str | None) -> str | None:
    if not entity_id:
        return "source_required"
    object_id = entity_id.split(".", 1)[1] if "." in entity_id else entity_id
    if object_id.startswith("doems_"):
        return "doems_source_not_allowed"
    return None if hass.states.get(entity_id) is not None else "source_not_found"

def _valid_iso_date(value: Any) -> bool:
    try:
        date.fromisoformat(str(value))
        return True
    except (TypeError, ValueError):
        return False


class DOEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 4

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DOEMSOptionsFlow(config_entry)


class DOEMSOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._pending: dict[str, Any] = dict(config_entry.options)
        self._solar_groups: list[dict[str, Any]] = []
        self._solar_arrays: list[dict[str, Any]] = []
        self._solar_group_index = 0
        self._solar_array_index = 0

    def _current(self, key: str, default: Any = None) -> Any:
        return self._pending.get(key, default)

    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(title="", data=self._pending)

    async def _after_energy(self) -> ConfigFlowResult:
        if self._pending.get(CONF_SOLAR_FOUNDATION_ENABLED, False):
            return await self.async_step_solar_system()
        if self._pending.get(CONF_PRICES_ENABLED, False):
            return await self.async_step_prices_general()
        return self._save()

    async def _after_solar(self) -> ConfigFlowResult:
        if self._pending.get(CONF_PRICES_ENABLED, False):
            return await self.async_step_prices_general()
        return self._save()

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._pending.update(user_input)
            if self._pending.get(CONF_ENERGY_FORECAST_ENABLED, False):
                return await self.async_step_energy_forecast()
            if self._pending.get(CONF_SOLAR_FOUNDATION_ENABLED, False):
                return await self.async_step_solar_system()
            if self._pending.get(CONF_PRICES_ENABLED, False):
                return await self.async_step_prices_general()
            return self._save()
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Optional(CONF_INSTANCE_NAME, default=self._current(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME)): str,
            vol.Required(CONF_ENERGY_FORECAST_ENABLED, default=bool(self._current(CONF_ENERGY_FORECAST_ENABLED, False))): bool,
            vol.Required(CONF_SOLAR_FOUNDATION_ENABLED, default=bool(self._current(CONF_SOLAR_FOUNDATION_ENABLED, False))): bool,
            vol.Required(CONF_PRICES_ENABLED, default=bool(self._current(CONF_PRICES_ENABLED, False))): bool,
        }))

    async def async_step_energy_forecast(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._pending.update(user_input)
            return await (self.async_step_energy_direct() if user_input[CONF_ENERGY_SOURCE_MODE] == ENERGY_SOURCE_DIRECT else self.async_step_energy_balance())
        return self.async_show_form(step_id="energy_forecast", data_schema=vol.Schema({
            vol.Required(CONF_ENERGY_SOURCE_MODE, default=self._current(CONF_ENERGY_SOURCE_MODE, ENERGY_SOURCE_DIRECT)): _select([
                (ENERGY_SOURCE_DIRECT, "Direct Home Power"), (ENERGY_SOURCE_BALANCE,