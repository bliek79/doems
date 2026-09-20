"""Config and options flow for DOEMS."""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_CHARGE_POWER_ENTITY,
    CONF_BATTERY_DISCHARGE_POWER_ENTITY,
    CONF_BATTERY_PRESENT,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_TECHNICAL_MIN_SOC_PERCENT,
    CONF_MAX_SOC_PERCENT,
    CONF_MAX_CHARGE_POWER_W,
    CONF_MAX_DISCHARGE_POWER_W,
    CONF_SOFTWARE_RESERVE_PERCENT,
    CONF_CHARGE_EFFICIENCY_PERCENT,
    CONF_DISCHARGE_EFFICIENCY_PERCENT,
    CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
    CONF_STARTUP_DELAY_SECONDS,
    CONF_AWAY_SCHEDULE_ENABLED,
    CONF_AWAY_START,
    CONF_AWAY_END,
    CONF_EMS_ENABLED,
    CONF_SOC_ENTITY,
    CONF_ELECTRICITY_EXPORT_SUPPLIER,
    CONF_ELECTRICITY_EXPORT_TAX,
    CONF_ELECTRICITY_FIXED_SUPPLY_PER_DAY,
    CONF_ELECTRICITY_GRID_PER_DAY,
    CONF_ELECTRICITY_IMPORT_SUPPLIER,
    CONF_ELECTRICITY_IMPORT_TAX,
    CONF_ELECTRICITY_TAX_CREDIT_PER_DAY,
    CONF_ENERGY_FORECAST_ENABLED,
    CONF_ENERGY_SOURCE_MODE,
    CONF_ENERGY_START_PROFILE,
    CONF_GAS_ENERGYZERO_CONFIG_ENTRY,
    CONF_GAS_FIXED_SUPPLY_PER_DAY,
    CONF_GAS_GRID_PER_DAY,
    CONF_GAS_MARKET_ENTITY,
    CONF_GAS_PRICES_ENABLED,
    CONF_GAS_SOURCE_MODE,
    CONF_GAS_SUPPLIER,
    CONF_GAS_TAX,
    CONF_GRID_NET_POWER_ENTITY,
    CONF_GRID_SIGN_CONVENTION,
    CONF_HOME_POWER_ENTITY,
    CONF_INSTANCE_NAME,
    CONF_PRICES_ENABLED,
    CONF_PRICES_RESOLUTION_PREFERENCE,
    CONF_SOLAR_ARRAY_COUNT,
    CONF_SOLAR_ARRAYS,
    CONF_SOLAR_FOUNDATION_ENABLED,
    CONF_SOLAR_INVERTER_GROUP_COUNT,
    CONF_SOLAR_INVERTER_GROUPS,
    CONF_SOLAR_LATITUDE,
    CONF_SOLAR_LOCATION_SOURCE,
    CONF_SOLAR_LONGITUDE,
    CONF_SOLAR_POWER_ENTITY,
    CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY,
    CONF_TARIFF_PROFILE_ID,
    CONF_TARIFF_SUPPLIER,
    CONF_TARIFF_VALID_FROM,
    CONF_VAT_PERCENT,
    DEFAULT_INSTANCE_NAME,
    DEFAULT_BATTERY_CAPACITY_KWH,
    DEFAULT_TECHNICAL_MIN_SOC_PERCENT,
    DEFAULT_MAX_SOC_PERCENT,
    DEFAULT_MAX_CHARGE_POWER_W,
    DEFAULT_MAX_DISCHARGE_POWER_W,
    DEFAULT_SOFTWARE_RESERVE_PERCENT,
    DEFAULT_CHARGE_EFFICIENCY_PERCENT,
    DEFAULT_DISCHARGE_EFFICIENCY_PERCENT,
    DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
    DEFAULT_STARTUP_DELAY_SECONDS,
    EMS_MIN_STARTUP_DELAY_SECONDS,
    EMS_MAX_STARTUP_DELAY_SECONDS,
    EMS_MAX_POWER_W,
    DOMAIN,
    ENERGY_SOURCE_BALANCE,
    ENERGY_SOURCE_DIRECT,
    GAS_SOURCE_ENERGYZERO_MARKET_ACTION,
    GAS_SOURCE_HOME_ASSISTANT_ENTITY,
    GRID_SIGN_POSITIVE_EXPORT,
    GRID_SIGN_POSITIVE_IMPORT,
    NAME,
    PRICES_RESOLUTION_15_MIN,
    PRICES_RESOLUTION_60_MIN,
    PRICES_RESOLUTION_AUTO,
    SOLAR_LOCATION_HOME_ASSISTANT,
    SOLAR_LOCATION_OVERRIDE,
    SOLAR_MAX_ARRAYS,
    SOLAR_MAX_INVERTER_GROUPS,
)
from .energy_sources import normalize_power_w
from .ems_config_validation import EMS_VALIDATED_FIELDS, validate_ems_combination, validate_ems_field
from .solar_foundation_model import validate_solar_foundation


def _power_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _sensor_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _energyzero_config_entry_selector() -> selector.ConfigEntrySelector:
    return selector.ConfigEntrySelector({"integration": "energyzero"})


def _select(options: list[tuple[str, str]]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=value, label=label) for value, label in options],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _number(
    minimum: float,
    maximum: float,
    step: float | Literal["any"],
    unit: str | None = None,
) -> selector.NumberSelector:
    config: selector.NumberSelectorConfig = {
        "min": minimum,
        "max": maximum,
        "step": step,
        "mode": selector.NumberSelectorMode.BOX,
    }
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _required_entity(key: str, current: str | None) -> vol.Marker:
    return vol.Required(key, default=current) if current else vol.Required(key)


def _optional_entity(key: str, current: str | None) -> vol.Marker:
    return vol.Optional(key, default=current) if current else vol.Optional(key)


def _optional_config_entry(key: str, current: str | None) -> vol.Marker:
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



def _validate_soc_entity(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Validate an optional generic read-only SOC percentage sensor."""
    if not entity_id:
        return None
    object_id = entity_id.split(".", 1)[1] if "." in entity_id else entity_id
    if object_id.startswith("doems_"):
        return "doems_source_not_allowed"
    state = hass.states.get(entity_id)
    if state is None:
        return "source_not_found"
    if state.attributes.get("unit_of_measurement") != "%":
        return "unsupported_soc_unit"
    if state.state not in {"unknown", "unavailable", "none", "None", ""}:
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return "invalid_soc_value"
        if not 0.0 <= value <= 100.0:
            return "invalid_soc_value"
    return None


def _validate_gas_market_entity(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Validate a generic gas source as an explicit EUR/m3 market-price sensor."""
    if not entity_id:
        return "source_required"
    object_id = entity_id.split(".", 1)[1] if "." in entity_id else entity_id
    if object_id.startswith("doems_"):
        return "doems_source_not_allowed"
    state = hass.states.get(entity_id)
    if state is None:
        return "source_not_found"
    unit = str(state.attributes.get("unit_of_measurement") or "")
    normalized_unit = (
        unit.replace("€", "EUR").replace("³", "3").replace(" ", "").lower()
    )
    if normalized_unit != "eur/m3":
        return "unsupported_gas_price_unit"
    return None


class DOEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 5

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
        # Away/profile runtime state is owned by PresenceStore entities, not Options.
        for key in (
            CONF_AWAY_SCHEDULE_ENABLED,
            CONF_AWAY_START,
            CONF_AWAY_END,
            CONF_ENERGY_START_PROFILE,
        ):
            self._pending.pop(key, None)
        return self.async_create_entry(title="", data=self._pending)

    async def _continue_after_energy(self) -> ConfigFlowResult:
        if self._pending.get(CONF_SOLAR_FOUNDATION_ENABLED, False):
            return await self.async_step_solar_system()
        if self._pending.get(CONF_PRICES_ENABLED, False):
            return await self.async_step_prices()
        if self._pending.get(CONF_EMS_ENABLED, False):
            return await self.async_step_ems()
        return self._save()

    async def _continue_after_solar(self) -> ConfigFlowResult:
        if self._pending.get(CONF_PRICES_ENABLED, False):
            return await self.async_step_prices()
        if self._pending.get(CONF_EMS_ENABLED, False):
            return await self.async_step_ems()
        return self._save()

    async def _continue_after_prices(self) -> ConfigFlowResult:
        if self._pending.get(CONF_EMS_ENABLED, False):
            return await self.async_step_ems()
        return self._save()

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._pending.update(user_input)
            if self._pending.get(CONF_ENERGY_FORECAST_ENABLED, False):
                return await self.async_step_energy_forecast()
            if self._pending.get(CONF_SOLAR_FOUNDATION_ENABLED, False):
                return await self.async_step_solar_system()
            if self._pending.get(CONF_PRICES_ENABLED, False):
                return await self.async_step_prices()
            if self._pending.get(CONF_EMS_ENABLED, False):
                return await self.async_step_ems()
            return self._save()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_INSTANCE_NAME, default=self._current(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME)): str,
                vol.Required(CONF_ENERGY_FORECAST_ENABLED, default=bool(self._current(CONF_ENERGY_FORECAST_ENABLED, False))): bool,
                vol.Required(CONF_SOLAR_FOUNDATION_ENABLED, default=bool(self._current(CONF_SOLAR_FOUNDATION_ENABLED, False))): bool,
                vol.Required(CONF_PRICES_ENABLED, default=bool(self._current(CONF_PRICES_ENABLED, False))): bool,
                vol.Required(CONF_EMS_ENABLED, default=bool(self._current(CONF_EMS_ENABLED, False))): bool,
            }),
        )

    async def async_step_energy_forecast(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._pending.update(user_input)
            self._pending.pop(CONF_ENERGY_START_PROFILE, None)
            if user_input[CONF_ENERGY_SOURCE_MODE] == ENERGY_SOURCE_DIRECT:
                return await self.async_step_energy_direct()
            return await self.async_step_energy_balance()
        return self.async_show_form(
            step_id="energy_forecast",
            data_schema=vol.Schema({
                vol.Required(CONF_ENERGY_SOURCE_MODE, default=self._current(CONF_ENERGY_SOURCE_MODE, ENERGY_SOURCE_DIRECT)): _select([
                    (ENERGY_SOURCE_DIRECT, "Direct Home Power"),
                    (ENERGY_SOURCE_BALANCE, "Power Balance"),
                ]),
            }),
        )

    async def async_step_energy_direct(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            error = _validate_power_entity(self.hass, user_input.get(CONF_HOME_POWER_ENTITY), allow_negative=False)
            if error:
                errors[CONF_HOME_POWER_ENTITY] = error
            else:
                self._pending.update(user_input)
                self._pending[CONF_BATTERY_PRESENT] = False
                for key in (CONF_GRID_NET_POWER_ENTITY, CONF_GRID_SIGN_CONVENTION, CONF_SOLAR_POWER_ENTITY, CONF_BATTERY_CHARGE_POWER_ENTITY, CONF_BATTERY_DISCHARGE_POWER_ENTITY):
                    self._pending.pop(key, None)
                return await self._continue_after_energy()
        return self.async_show_form(
            step_id="energy_direct",
            data_schema=vol.Schema({_required_entity(CONF_HOME_POWER_ENTITY, self._current(CONF_HOME_POWER_ENTITY)): _power_selector()}),
            errors=errors,
        )

    async def async_step_energy_balance(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            for key, allow_negative in ((CONF_GRID_NET_POWER_ENTITY, True), (CONF_SOLAR_POWER_ENTITY, False)):
                error = _validate_power_entity(self.hass, user_input.get(key), allow_negative=allow_negative)
                if error:
                    errors[key] = error
            if not errors:
                self._pending.update(user_input)
                self._pending.pop(CONF_HOME_POWER_ENTITY, None)
                if user_input.get(CONF_BATTERY_PRESENT):
                    return await self.async_step_energy_battery()
                self._pending.pop(CONF_BATTERY_CHARGE_POWER_ENTITY, None)
                self._pending.pop(CONF_BATTERY_DISCHARGE_POWER_ENTITY, None)
                return await self._continue_after_energy()
        return self.async_show_form(
            step_id="energy_balance",
            data_schema=vol.Schema({
                _required_entity(CONF_GRID_NET_POWER_ENTITY, self._current(CONF_GRID_NET_POWER_ENTITY)): _power_selector(),
                vol.Required(CONF_GRID_SIGN_CONVENTION, default=self._current(CONF_GRID_SIGN_CONVENTION, GRID_SIGN_POSITIVE_IMPORT)): _select([
                    (GRID_SIGN_POSITIVE_IMPORT, "Positive import / negative export"),
                    (GRID_SIGN_POSITIVE_EXPORT, "Positive export / negative import"),
                ]),
                _required_entity(CONF_SOLAR_POWER_ENTITY, self._current(CONF_SOLAR_POWER_ENTITY)): _power_selector(),
                vol.Required(CONF_BATTERY_PRESENT, default=bool(self._current(CONF_BATTERY_PRESENT, False))): bool,
            }),
            errors=errors,
        )

    async def async_step_energy_battery(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            for key in (CONF_BATTERY_CHARGE_POWER_ENTITY, CONF_BATTERY_DISCHARGE_POWER_ENTITY):
                error = _validate_power_entity(self.hass, user_input.get(key), allow_negative=False)
                if error:
                    errors[key] = error
            if not errors:
                self._pending.update(user_input)
                return await self._continue_after_energy()
        return self.async_show_form(
            step_id="energy_battery",
            data_schema=vol.Schema({
                _required_entity(CONF_BATTERY_CHARGE_POWER_ENTITY, self._current(CONF_BATTERY_CHARGE_POWER_ENTITY)): _power_selector(),
                _required_entity(CONF_BATTERY_DISCHARGE_POWER_ENTITY, self._current(CONF_BATTERY_DISCHARGE_POWER_ENTITY)): _power_selector(),
            }),
            errors=errors,
        )

    async def async_step_solar_system(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            total_actual = user_input.get(CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY)
            if total_actual:
                error = _validate_power_entity(self.hass, total_actual, allow_negative=False)
                if error:
                    errors[CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY] = error
            if not errors:
                self._pending.update(user_input)
                if not total_actual:
                    self._pending.pop(CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY, None)
                if user_input[CONF_SOLAR_LOCATION_SOURCE] == SOLAR_LOCATION_OVERRIDE:
                    return await self.async_step_solar_location_override()
                self._pending.pop(CONF_SOLAR_LATITUDE, None)
                self._pending.pop(CONF_SOLAR_LONGITUDE, None)
                self._prepare_solar_topology()
                return await self.async_step_solar_inverter_group()
        return self.async_show_form(
            step_id="solar_system",
            data_schema=vol.Schema({
                vol.Required(CONF_SOLAR_LOCATION_SOURCE, default=self._current(CONF_SOLAR_LOCATION_SOURCE, SOLAR_LOCATION_HOME_ASSISTANT)): _select([
                    (SOLAR_LOCATION_HOME_ASSISTANT, "Home Assistant location"),
                    (SOLAR_LOCATION_OVERRIDE, "Override location"),
                ]),
                vol.Required(CONF_SOLAR_INVERTER_GROUP_COUNT, default=int(self._current(CONF_SOLAR_INVERTER_GROUP_COUNT, max(1, len(self._current(CONF_SOLAR_INVERTER_GROUPS, [])))))): _number(1, SOLAR_MAX_INVERTER_GROUPS, 1),
                vol.Required(CONF_SOLAR_ARRAY_COUNT, default=int(self._current(CONF_SOLAR_ARRAY_COUNT, max(1, len(self._current(CONF_SOLAR_ARRAYS, [])))))): _number(1, SOLAR_MAX_ARRAYS, 1),
                _optional_entity(CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY, self._current(CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY)): _power_selector(),
            }),
            errors=errors,
        )

    async def async_step_solar_location_override(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._pending.update(user_input)
            self._prepare_solar_topology()
            return await self.async_step_solar_inverter_group()
        return self.async_show_form(
            step_id="solar_location_override",
            data_schema=vol.Schema({
                vol.Required(CONF_SOLAR_LATITUDE, default=float(self._current(CONF_SOLAR_LATITUDE, self.hass.config.latitude))): _number(-90, 90, "any", "°"),
                vol.Required(CONF_SOLAR_LONGITUDE, default=float(self._current(CONF_SOLAR_LONGITUDE, self.hass.config.longitude))): _number(-180, 180, "any", "°"),
            }),
        )

    def _prepare_solar_topology(self) -> None:
        group_count = int(self._pending[CONF_SOLAR_INVERTER_GROUP_COUNT])
        array_count = int(self._pending[CONF_SOLAR_ARRAY_COUNT])
        existing_groups = self._pending.get(CONF_SOLAR_INVERTER_GROUPS, [])
        existing_arrays = self._pending.get(CONF_SOLAR_ARRAYS, [])
        self._solar_groups = [dict(item) for item in existing_groups[:group_count] if isinstance(item, dict)]
        self._solar_arrays = [dict(item) for item in existing_arrays[:array_count] if isinstance(item, dict)]
        self._solar_group_index = 0
        self._solar_array_index = 0

    async def async_step_solar_inverter_group(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        index = self._solar_group_index
        count = int(self._pending[CONF_SOLAR_INVERTER_GROUP_COUNT])
        existing = self._solar_groups[index] if index < len(self._solar_groups) else {}
        if user_input is not None:
            group_id = str(existing.get("group_id") or f"inv_{uuid4().hex[:12]}")
            item = {
                "group_id": group_id,
                "name": str(user_input["name"]).strip() or f"Inverter {index + 1}",
                "ac_limit_kw": float(user_input["ac_limit_kw"]),
            }
            if index < len(self._solar_groups): self._solar_groups[index] = item
            else: self._solar_groups.append(item)
            self._solar_group_index += 1
            if self._solar_group_index < count:
                return await self.async_step_solar_inverter_group()
            self._solar_groups = self._solar_groups[:count]
            self._solar_array_index = 0
            return await self.async_step_solar_array()
        return self.async_show_form(
            step_id="solar_inverter_group",
            description_placeholders={"index": str(index + 1), "count": str(count)},
            data_schema=vol.Schema({
                vol.Required("name", default=str(existing.get("name") or f"Inverter {index + 1}")): str,
                vol.Required("ac_limit_kw", default=float(existing.get("ac_limit_kw", 0.0))): _number(0, 100, 0.01, "kW"),
            }),
        )

    async def async_step_solar_array(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        index = self._solar_array_index
        count = int(self._pending[CONF_SOLAR_ARRAY_COUNT])
        existing = self._solar_arrays[index] if index < len(self._solar_arrays) else {}
        group_options = [(str(g["group_id"]), str(g.get("name") or g["group_id"])) for g in self._solar_groups]
        valid_group_ids = {value for value, _ in group_options}
        default_group = str(existing.get("group_id") or group_options[0][0])
        if default_group not in valid_group_ids: default_group = group_options[0][0]
        errors: dict[str, str] = {}
        if user_input is not None:
            actual = user_input.get("actual_power_entity")
            if actual:
                error = _validate_power_entity(self.hass, actual, allow_negative=False)
                if error: errors["actual_power_entity"] = error
                previous_actuals = {str(item.get("actual_power_entity")) for item in self._solar_arrays[:index] if item.get("actual_power_entity")}
                if actual in previous_actuals: errors["actual_power_entity"] = "duplicate_actual_source"
                total_actual = self._pending.get(CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY)
                if count > 1 and total_actual and actual == total_actual: errors["actual_power_entity"] = "total_actual_reused_as_array"
            if not errors:
                array_id = str(existing.get("array_id") or f"arr_{uuid4().hex[:12]}")
                item = {
                    "array_id": array_id,
                    "name": str(user_input["name"]).strip() or f"Array {index + 1}",
                    "group_id": str(user_input["group_id"]),
                    "dc_kwp": float(user_input["dc_kwp"]),
                    "tilt_deg": float(user_input["tilt_deg"]),
                    "azimuth_deg": float(user_input["azimuth_deg"]),
                    "actual_power_entity": str(actual) if actual else None,
                }
                if index < len(self._solar_arrays): self._solar_arrays[index] = item
                else: self._solar_arrays.append(item)
                if index + 1 < count:
                    self._solar_array_index = index + 1
                    return await self.async_step_solar_array()
                # Keep the cursor pinned to the last configured array while
                # transitioning to the next options step. If a later form
                # cannot render, Home Assistant must never expose a phantom
                # "array 3 of 2" screen.
                self._solar_array_index = max(0, count - 1)
                self._solar_arrays = self._solar_arrays[:count]
                self._pending[CONF_SOLAR_INVERTER_GROUPS] = self._solar_groups
                self._pending[CONF_SOLAR_ARRAYS] = self._solar_arrays
                blockers = validate_solar_foundation(self._pending, ha_latitude=self.hass.config.latitude, ha_longitude=self.hass.config.longitude)
                if blockers:
                    return self.async_abort(reason="solar_foundation_invalid")
                return await self._continue_after_solar()
        return self.async_show_form(
            step_id="solar_array",
            description_placeholders={"index": str(index + 1), "count": str(count)},
            data_schema=vol.Schema({
                vol.Required("name", default=str(existing.get("name") or f"Array {index + 1}")): str,
                vol.Required("group_id", default=default_group): _select(group_options),
                vol.Required("dc_kwp", default=float(existing.get("dc_kwp", 1.0))): _number(0.01, 100, 0.01, "kWp"),
                vol.Required("tilt_deg", default=float(existing.get("tilt_deg", 30.0))): _number(0, 90, 0.1, "°"),
                vol.Required("azimuth_deg", default=float(existing.get("azimuth_deg", 180.0))): _number(0, 359.9, 0.1, "°"),
                _optional_entity("actual_power_entity", existing.get("actual_power_entity")): _power_selector(),
            }),
            errors=errors,
        )

    async def async_step_ems(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure and individually validate the G6 EMS settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            for key in EMS_VALIDATED_FIELDS:
                if key in user_input:
                    error = validate_ems_field(key, user_input[key])
                    if error:
                        errors[key] = error
            soc_error = _validate_soc_entity(self.hass, user_input.get(CONF_SOC_ENTITY))
            if soc_error:
                errors[CONF_SOC_ENTITY] = soc_error
            if not errors:
                normalized = dict(user_input)
                errors.update(validate_ems_combination(normalized))
                if not errors:
                    self._pending.update(normalized)
                    if not normalized.get(CONF_SOC_ENTITY):
                        self._pending.pop(CONF_SOC_ENTITY, None)
                    return self._save()

        return self.async_show_form(
            step_id="ems",
            data_schema=vol.Schema({
                _optional_entity(CONF_SOC_ENTITY, self._current(CONF_SOC_ENTITY)): _sensor_selector(),
                vol.Required(
                    CONF_BATTERY_CAPACITY_KWH,
                    default=float(self._current(CONF_BATTERY_CAPACITY_KWH, DEFAULT_BATTERY_CAPACITY_KWH)),
                ): _number(1.0, 30.0, 0.1, "kWh"),
                vol.Required(
                    CONF_TECHNICAL_MIN_SOC_PERCENT,
                    default=int(self._current(CONF_TECHNICAL_MIN_SOC_PERCENT, DEFAULT_TECHNICAL_MIN_SOC_PERCENT)),
                ): _number(0, 30, 1, "%"),
                vol.Required(
                    CONF_MAX_SOC_PERCENT,
                    default=int(self._current(CONF_MAX_SOC_PERCENT, DEFAULT_MAX_SOC_PERCENT)),
                ): _number(50, 100, 1, "%"),
                vol.Required(
                    CONF_MAX_CHARGE_POWER_W,
                    default=int(self._current(CONF_MAX_CHARGE_POWER_W, DEFAULT_MAX_CHARGE_POWER_W)),
                ): _number(100, EMS_MAX_POWER_W, 100, "W"),
                vol.Required(
                    CONF_MAX_DISCHARGE_POWER_W,
                    default=int(self._current(CONF_MAX_DISCHARGE_POWER_W, DEFAULT_MAX_DISCHARGE_POWER_W)),
                ): _number(100, EMS_MAX_POWER_W, 100, "W"),
                vol.Required(
                    CONF_SOFTWARE_RESERVE_PERCENT,
                    default=float(self._current(CONF_SOFTWARE_RESERVE_PERCENT, DEFAULT_SOFTWARE_RESERVE_PERCENT)),
                ): _number(0, 30, 1, "%"),
                vol.Required(
                    CONF_CHARGE_EFFICIENCY_PERCENT,
                    default=float(self._current(CONF_CHARGE_EFFICIENCY_PERCENT, DEFAULT_CHARGE_EFFICIENCY_PERCENT)),
                ): _number(50, 100, 1, "%"),
                vol.Required(
                    CONF_DISCHARGE_EFFICIENCY_PERCENT,
                    default=float(self._current(CONF_DISCHARGE_EFFICIENCY_PERCENT, DEFAULT_DISCHARGE_EFFICIENCY_PERCENT)),
                ): _number(50, 100, 1, "%"),
                vol.Required(
                    CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
                    default=float(self._current(CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH, DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH)),
                ): _number(0.0, 1.0, 0.01, "EUR/kWh"),
                vol.Required(
                    CONF_STARTUP_DELAY_SECONDS,
                    default=int(self._current(CONF_STARTUP_DELAY_SECONDS, DEFAULT_STARTUP_DELAY_SECONDS)),
                ): _number(EMS_MIN_STARTUP_DELAY_SECONDS, EMS_MAX_STARTUP_DELAY_SECONDS, 5, "s"),
            }),
            errors=errors,
        )

    async def async_step_prices(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure provider-neutral electricity tariff inputs for Prices P4."""
        if user_input is not None:
            self._pending.update(user_input)
            if user_input.get(CONF_GAS_PRICES_ENABLED, False):
                return await self.async_step_prices_gas()
            for key in (
                CONF_GAS_SOURCE_MODE,
                CONF_GAS_MARKET_ENTITY,
                CONF_GAS_ENERGYZERO_CONFIG_ENTRY,
                CONF_GAS_SUPPLIER,
                CONF_GAS_TAX,
                CONF_GAS_FIXED_SUPPLY_PER_DAY,
                CONF_GAS_GRID_PER_DAY,
            ):
                self._pending.pop(key, None)
            return await self._continue_after_prices()
        return self.async_show_form(
            step_id="prices",
            data_schema=vol.Schema({
                vol.Required(CONF_PRICES_RESOLUTION_PREFERENCE, default=self._current(CONF_PRICES_RESOLUTION_PREFERENCE, PRICES_RESOLUTION_AUTO)): _select([
                    (PRICES_RESOLUTION_AUTO, "Auto - prefer 15 minute known prices"),
                    (PRICES_RESOLUTION_15_MIN, "15 minute known prices"),
                    (PRICES_RESOLUTION_60_MIN, "Hourly known prices"),
                ]),
                vol.Required(CONF_TARIFF_PROFILE_ID, default=str(self._current(CONF_TARIFF_PROFILE_ID, "current"))): str,
                vol.Required(CONF_TARIFF_SUPPLIER, default=str(self._current(CONF_TARIFF_SUPPLIER, "unconfigured"))): str,
                vol.Optional(CONF_TARIFF_VALID_FROM, default=str(self._current(CONF_TARIFF_VALID_FROM, ""))): str,
                vol.Required(CONF_VAT_PERCENT, default=float(self._current(CONF_VAT_PERCENT, 21.0))): _number(0, 100, 0.01, "%"),
                vol.Required(CONF_ELECTRICITY_IMPORT_SUPPLIER, default=float(self._current(CONF_ELECTRICITY_IMPORT_SUPPLIER, 0.0))): _number(-10, 10, "any", "EUR/kWh"),
                vol.Required(CONF_ELECTRICITY_IMPORT_TAX, default=float(self._current(CONF_ELECTRICITY_IMPORT_TAX, 0.0))): _number(-10, 10, "any", "EUR/kWh"),
                vol.Required(CONF_ELECTRICITY_EXPORT_SUPPLIER, default=float(self._current(CONF_ELECTRICITY_EXPORT_SUPPLIER, 0.0))): _number(-10, 10, "any", "EUR/kWh"),
                vol.Required(CONF_ELECTRICITY_EXPORT_TAX, default=float(self._current(CONF_ELECTRICITY_EXPORT_TAX, 0.0))): _number(-10, 10, "any", "EUR/kWh"),
                vol.Required(CONF_ELECTRICITY_FIXED_SUPPLY_PER_DAY, default=float(self._current(CONF_ELECTRICITY_FIXED_SUPPLY_PER_DAY, 0.0))): _number(-100, 100, "any", "EUR/day"),
                vol.Required(CONF_ELECTRICITY_GRID_PER_DAY, default=float(self._current(CONF_ELECTRICITY_GRID_PER_DAY, 0.0))): _number(-100, 100, "any", "EUR/day"),
                vol.Required(CONF_ELECTRICITY_TAX_CREDIT_PER_DAY, default=float(self._current(CONF_ELECTRICITY_TAX_CREDIT_PER_DAY, 0.0))): _number(-100, 100, "any", "EUR/day"),
                vol.Required(CONF_GAS_PRICES_ENABLED, default=bool(self._current(CONF_GAS_PRICES_ENABLED, False))): bool,
            }),
        )

    async def async_step_prices_gas(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure explicit gas market-price source semantics."""
        errors: dict[str, str] = {}
        if user_input is not None:
            source_mode = str(
                user_input.get(
                    CONF_GAS_SOURCE_MODE,
                    GAS_SOURCE_HOME_ASSISTANT_ENTITY,
                )
            )
            if source_mode == GAS_SOURCE_ENERGYZERO_MARKET_ACTION:
                entry_id = user_input.get(CONF_GAS_ENERGYZERO_CONFIG_ENTRY)
                energyzero_entry = (
                    self.hass.config_entries.async_get_entry(str(entry_id))
                    if entry_id
                    else None
                )
                if energyzero_entry is None or energyzero_entry.domain != "energyzero":
                    errors[CONF_GAS_ENERGYZERO_CONFIG_ENTRY] = "energyzero_config_entry_required"
            else:
                error = _validate_gas_market_entity(
                    self.hass, user_input.get(CONF_GAS_MARKET_ENTITY)
                )
                if error:
                    errors[CONF_GAS_MARKET_ENTITY] = error

            if not errors:
                self._pending.update(user_input)
                if source_mode == GAS_SOURCE_ENERGYZERO_MARKET_ACTION:
                    self._pending.pop(CONF_GAS_MARKET_ENTITY, None)
                else:
                    self._pending.pop(CONF_GAS_ENERGYZERO_CONFIG_ENTRY, None)
                return await self._continue_after_prices()

        current_mode = str(
            self._current(CONF_GAS_SOURCE_MODE, GAS_SOURCE_HOME_ASSISTANT_ENTITY)
        )
        return self.async_show_form(
            step_id="prices_gas",
            data_schema=vol.Schema({
                vol.Required(CONF_GAS_SOURCE_MODE, default=current_mode): _select([
                    (
                        GAS_SOURCE_ENERGYZERO_MARKET_ACTION,
                        "EnergyZero market action - explicit market incl. VAT",
                    ),
                    (
                        GAS_SOURCE_HOME_ASSISTANT_ENTITY,
                        "Home Assistant market-price sensor",
                    ),
                ]),
                _optional_config_entry(
                    CONF_GAS_ENERGYZERO_CONFIG_ENTRY,
                    self._current(CONF_GAS_ENERGYZERO_CONFIG_ENTRY),
                ): _energyzero_config_entry_selector(),
                _optional_entity(
                    CONF_GAS_MARKET_ENTITY,
                    self._current(CONF_GAS_MARKET_ENTITY),
                ): _sensor_selector(),
                vol.Required(CONF_GAS_SUPPLIER, default=float(self._current(CONF_GAS_SUPPLIER, 0.0))): _number(-10, 10, "any", "EUR/m3"),
                vol.Required(CONF_GAS_TAX, default=float(self._current(CONF_GAS_TAX, 0.0))): _number(-10, 10, "any", "EUR/m3"),
                vol.Required(CONF_GAS_FIXED_SUPPLY_PER_DAY, default=float(self._current(CONF_GAS_FIXED_SUPPLY_PER_DAY, 0.0))): _number(-100, 100, "any", "EUR/day"),
                vol.Required(CONF_GAS_GRID_PER_DAY, default=float(self._current(CONF_GAS_GRID_PER_DAY, 0.0))): _number(-100, 100, "any", "EUR/day"),
            }),
            errors=errors,
        )
