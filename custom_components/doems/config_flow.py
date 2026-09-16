"""Config and options flow for DOEMS."""

from __future__ import annotations

from typing import Any
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
    CONF_ENERGY_FORECAST_ENABLED,
    CONF_ENERGY_SOURCE_MODE,
    CONF_ENERGY_START_PROFILE,
    CONF_GRID_NET_POWER_ENTITY,
    CONF_GRID_SIGN_CONVENTION,
    CONF_HOME_POWER_ENTITY,
    CONF_INSTANCE_NAME,
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
    DEFAULT_INSTANCE_NAME,
    DOMAIN,
    ENERGY_SOURCE_BALANCE,
    ENERGY_SOURCE_DIRECT,
    GRID_SIGN_POSITIVE_EXPORT,
    GRID_SIGN_POSITIVE_IMPORT,
    NAME,
    PROFILE_AWAY,
    PROFILE_NORMAL,
    SOLAR_LOCATION_HOME_ASSISTANT,
    SOLAR_LOCATION_OVERRIDE,
    SOLAR_MAX_ARRAYS,
    SOLAR_MAX_INVERTER_GROUPS,
)
from .energy_sources import normalize_power_w
from .solar_foundation_model import validate_solar_foundation


def _power_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


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
    step: float,
    unit: str | None = None,
) -> selector.NumberSelector:
    """Build a numeric selector without serializing a null unit."""
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


def _validate_power_entity(
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    allow_negative: bool,
) -> str | None:
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


class DOEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the clean DOEMS config entry."""

    VERSION = 1
    MINOR_VERSION = 3

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the clean DOEMS config entry without site-specific inputs."""
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
    """Configure one DOEMS component at a time."""

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

    async def _finish_energy_or_continue(self) -> ConfigFlowResult:
        if self._pending.get(CONF_SOLAR_FOUNDATION_ENABLED, False):
            return await self.async_step_solar_system()
        return self._save()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select which currently implemented components are active."""
        if user_input is not None:
            self._pending.update(user_input)
            if self._pending.get(CONF_ENERGY_FORECAST_ENABLED, False):
                return await self.async_step_energy_forecast()
            if self._pending.get(CONF_SOLAR_FOUNDATION_ENABLED, False):
                return await self.async_step_solar_system()
            return self._save()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_INSTANCE_NAME,
                        default=self._current(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
                    ): str,
                    vol.Required(
                        CONF_ENERGY_FORECAST_ENABLED,
                        default=bool(self._current(CONF_ENERGY_FORECAST_ENABLED, False)),
                    ): bool,
                    vol.Required(
                        CONF_SOLAR_FOUNDATION_ENABLED,
                        default=bool(self._current(CONF_SOLAR_FOUNDATION_ENABLED, False)),
                    ): bool,
                }
            ),
        )

    async def async_step_energy_forecast(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the generic Energy Forecast source route and start profile."""
        if user_input is not None:
            self._pending.update(user_input)
            if user_input[CONF_ENERGY_SOURCE_MODE] == ENERGY_SOURCE_DIRECT:
                return await self.async_step_energy_direct()
            return await self.async_step_energy_balance()

        return self.async_show_form(
            step_id="energy_forecast",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENERGY_SOURCE_MODE,
                        default=self._current(CONF_ENERGY_SOURCE_MODE, ENERGY_SOURCE_DIRECT),
                    ): _select(
                        [
                            (ENERGY_SOURCE_DIRECT, "Direct Home Power"),
                            (ENERGY_SOURCE_BALANCE, "Power Balance"),
                        ]
                    ),
                    vol.Required(
                        CONF_ENERGY_START_PROFILE,
                        default=self._current(CONF_ENERGY_START_PROFILE, PROFILE_NORMAL),
                    ): _select(
                        [
                            (PROFILE_NORMAL, "Normal"),
                            (PROFILE_AWAY, "Away"),
                        ]
                    ),
                }
            ),
        )

    async def async_step_energy_direct(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a direct actual Home Power sensor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            error = _validate_power_entity(
                self.hass,
                user_input.get(CONF_HOME_POWER_ENTITY),
                allow_negative=False,
            )
            if error:
                errors[CONF_HOME_POWER_ENTITY] = error
            else:
                self._pending.update(user_input)
                self._pending[CONF_BATTERY_PRESENT] = False
                for key in (
                    CONF_GRID_NET_POWER_ENTITY,
                    CONF_GRID_SIGN_CONVENTION,
                    CONF_SOLAR_POWER_ENTITY,
                    CONF_BATTERY_CHARGE_POWER_ENTITY,
                    CONF_BATTERY_DISCHARGE_POWER_ENTITY,
                ):
                    self._pending.pop(key, None)
                return await self._finish_energy_or_continue()

        return self.async_show_form(
            step_id="energy_direct",
            data_schema=vol.Schema(
                {
                    _required_entity(
                        CONF_HOME_POWER_ENTITY, self._current(CONF_HOME_POWER_ENTITY)
                    ): _power_selector(),
                }
            ),
            errors=errors,
        )

    async def async_step_energy_balance(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the grid + solar + optional battery power balance."""
        errors: dict[str, str] = {}
        if user_input is not None:
            for key, allow_negative in (
                (CONF_GRID_NET_POWER_ENTITY, True),
                (CONF_SOLAR_POWER_ENTITY, False),
            ):
                error = _validate_power_entity(
                    self.hass, user_input.get(key), allow_negative=allow_negative
                )
                if error:
                    errors[key] = error
            if not errors:
                self._pending.update(user_input)
                self._pending.pop(CONF_HOME_POWER_ENTITY, None)
                if user_input.get(CONF_BATTERY_PRESENT):
                    return await self.async_step_energy_battery()
                self._pending.pop(CONF_BATTERY_CHARGE_POWER_ENTITY, None)
                self._pending.pop(CONF_BATTERY_DISCHARGE_POWER_ENTITY, None)
                return await self._finish_energy_or_continue()

        return self.async_show_form(
            step_id="energy_balance",
            data_schema=vol.Schema(
                {
                    _required_entity(
                        CONF_GRID_NET_POWER_ENTITY, self._current(CONF_GRID_NET_POWER_ENTITY)
                    ): _power_selector(),
                    vol.Required(
                        CONF_GRID_SIGN_CONVENTION,
                        default=self._current(
                            CONF_GRID_SIGN_CONVENTION, GRID_SIGN_POSITIVE_IMPORT
                        ),
                    ): _select(
                        [
                            (GRID_SIGN_POSITIVE_IMPORT, "Positive import / negative export"),
                            (GRID_SIGN_POSITIVE_EXPORT, "Positive export / negative import"),
                        ]
                    ),
                    _required_entity(
                        CONF_SOLAR_POWER_ENTITY, self._current(CONF_SOLAR_POWER_ENTITY)
                    ): _power_selector(),
                    vol.Required(
                        CONF_BATTERY_PRESENT,
                        default=bool(self._current(CONF_BATTERY_PRESENT, False)),
                    ): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_energy_battery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure positive battery charge/discharge power magnitudes."""
        errors: dict[str, str] = {}
        if user_input is not None:
            for key in (
                CONF_BATTERY_CHARGE_POWER_ENTITY,
                CONF_BATTERY_DISCHARGE_POWER_ENTITY,
            ):
                error = _validate_power_entity(
                    self.hass, user_input.get(key), allow_negative=False
                )
                if error:
                    errors[key] = error
            if not errors:
                self._pending.update(user_input)
                return await self._finish_energy_or_continue()

        return self.async_show_form(
            step_id="energy_battery",
            data_schema=vol.Schema(
                {
                    _required_entity(
                        CONF_BATTERY_CHARGE_POWER_ENTITY,
                        self._current(CONF_BATTERY_CHARGE_POWER_ENTITY),
                    ): _power_selector(),
                    _required_entity(
                        CONF_BATTERY_DISCHARGE_POWER_ENTITY,
                        self._current(CONF_BATTERY_DISCHARGE_POWER_ENTITY),
                    ): _power_selector(),
                }
            ),
            errors=errors,
        )

    async def async_step_solar_system(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure system-level Solar Foundation inputs."""
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
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SOLAR_LOCATION_SOURCE,
                        default=self._current(CONF_SOLAR_LOCATION_SOURCE, SOLAR_LOCATION_HOME_ASSISTANT),
                    ): _select(
                        [
                            (SOLAR_LOCATION_HOME_ASSISTANT, "Home Assistant location"),
                            (SOLAR_LOCATION_OVERRIDE, "Override location"),
                        ]
                    ),
                    vol.Required(
                        CONF_SOLAR_INVERTER_GROUP_COUNT,
                        default=int(self._current(CONF_SOLAR_INVERTER_GROUP_COUNT, max(1, len(self._current(CONF_SOLAR_INVERTER_GROUPS, []))))),
                    ): _number(1, SOLAR_MAX_INVERTER_GROUPS, 1),
                    vol.Required(
                        CONF_SOLAR_ARRAY_COUNT,
                        default=int(self._current(CONF_SOLAR_ARRAY_COUNT, max(1, len(self._current(CONF_SOLAR_ARRAYS, []))))),
                    ): _number(1, SOLAR_MAX_ARRAYS, 1),
                    _optional_entity(
                        CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY,
                        self._current(CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY),
                    ): _power_selector(),
                }
            ),
            errors=errors,
        )

    async def async_step_solar_location_override(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure an explicit Solar location instead of the HA location."""
        if user_input is not None:
            self._pending.update(user_input)
            self._prepare_solar_topology()
            return await self.async_step_solar_inverter_group()

        return self.async_show_form(
            step_id="solar_location_override",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SOLAR_LATITUDE,
                        default=float(self._current(CONF_SOLAR_LATITUDE, self.hass.config.latitude)),
                    ): _number(-90, 90, 0.000001, "°"),
                    vol.Required(
                        CONF_SOLAR_LONGITUDE,
                        default=float(self._current(CONF_SOLAR_LONGITUDE, self.hass.config.longitude)),
                    ): _number(-180, 180, 0.000001, "°"),
                }
            ),
        )

    def _prepare_solar_topology(self) -> None:
        """Prepare in-memory editing while preserving existing stable IDs by position."""
        group_count = int(self._pending[CONF_SOLAR_INVERTER_GROUP_COUNT])
        array_count = int(self._pending[CONF_SOLAR_ARRAY_COUNT])
        existing_groups = self._pending.get(CONF_SOLAR_INVERTER_GROUPS, [])
        existing_arrays = self._pending.get(CONF_SOLAR_ARRAYS, [])
        self._solar_groups = [dict(item) for item in existing_groups[:group_count] if isinstance(item, dict)]
        self._solar_arrays = [dict(item) for item in existing_arrays[:array_count] if isinstance(item, dict)]
        self._solar_group_index = 0
        self._solar_array_index = 0

    async def async_step_solar_inverter_group(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure one inverter group at a time."""
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
            if index < len(self._solar_groups):
                self._solar_groups[index] = item
            else:
                self._solar_groups.append(item)
            self._solar_group_index += 1
            if self._solar_group_index < count:
                return await self.async_step_solar_inverter_group()
            self._solar_groups = self._solar_groups[:count]
            self._solar_array_index = 0
            return await self.async_step_solar_array()

        return self.async_show_form(
            step_id="solar_inverter_group",
            description_placeholders={"index": str(index + 1), "count": str(count)},
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=str(existing.get("name") or f"Inverter {index + 1}")): str,
                    vol.Required("ac_limit_kw", default=float(existing.get("ac_limit_kw", 0.0))): _number(0, 100, 0.01, "kW"),
                }
            ),
        )

    async def async_step_solar_array(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure one PV array at a time with provider-neutral geometry."""
        index = self._solar_array_index
        count = int(self._pending[CONF_SOLAR_ARRAY_COUNT])
        existing = self._solar_arrays[index] if index < len(self._solar_arrays) else {}
        group_options = [
            (str(group["group_id"]), str(group.get("name") or group["group_id"]))
            for group in self._solar_groups
        ]
        valid_group_ids = {value for value, _label in group_options}
        default_group = str(existing.get("group_id") or group_options[0][0])
        if default_group not in valid_group_ids:
            default_group = group_options[0][0]
        errors: dict[str, str] = {}

        if user_input is not None:
            actual = user_input.get("actual_power_entity")
            if actual:
                error = _validate_power_entity(self.hass, actual, allow_negative=False)
                if error:
                    errors["actual_power_entity"] = error
                previous_actuals = {
                    str(item.get("actual_power_entity"))
                    for item in self._solar_arrays[:index]
                    if item.get("actual_power_entity")
                }
                if actual in previous_actuals:
                    errors["actual_power_entity"] = "duplicate_actual_source"
                total_actual = self._pending.get(CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY)
                if count > 1 and total_actual and actual == total_actual:
                    errors["actual_power_entity"] = "total_actual_reused_as_array"
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
                if index < len(self._solar_arrays):
                    self._solar_arrays[index] = item
                else:
                    self._solar_arrays.append(item)
                self._solar_array_index += 1
                if self._solar_array_index < count:
                    return await self.async_step_solar_array()

                self._solar_arrays = self._solar_arrays[:count]
                self._pending[CONF_SOLAR_INVERTER_GROUPS] = self._solar_groups
                self._pending[CONF_SOLAR_ARRAYS] = self._solar_arrays
                blockers = validate_solar_foundation(
                    self._pending,
                    ha_latitude=self.hass.config.latitude,
                    ha_longitude=self.hass.config.longitude,
                )
                if blockers:
                    return self.async_abort(reason="solar_foundation_invalid")
                return self._save()

        return self.async_show_form(
            step_id="solar_array",
            description_placeholders={"index": str(index + 1), "count": str(count)},
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=str(existing.get("name") or f"Array {index + 1}")): str,
                    vol.Required("group_id", default=default_group): _select(group_options),
                    vol.Required("dc_kwp", default=float(existing.get("dc_kwp", 1.0))): _number(0.01, 100, 0.01, "kWp"),
                    vol.Required("tilt_deg", default=float(existing.get("tilt_deg", 30.0))): _number(0, 90, 0.1, "°"),
                    vol.Required("azimuth_deg", default=float(existing.get("azimuth_deg", 180.0))): _number(0, 359.9, 0.1, "°"),
                    _optional_entity("actual_power_entity", existing.get("actual_power_entity")): _power_selector(),
                }
            ),
            errors=errors,
        )
