"""Config and options flow for DOEMS."""

from __future__ import annotations

from typing import Any

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
    CONF_SOLAR_POWER_ENTITY,
    DEFAULT_INSTANCE_NAME,
    DOMAIN,
    ENERGY_SOURCE_BALANCE,
    ENERGY_SOURCE_DIRECT,
    GRID_SIGN_POSITIVE_EXPORT,
    GRID_SIGN_POSITIVE_IMPORT,
    NAME,
    PROFILE_AWAY,
    PROFILE_NORMAL,
)
from .energy_sources import normalize_power_w


def _power_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _select(options: list[tuple[str, str]]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=value, label=label) for value, label in options],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _required_entity(key: str, current: str | None) -> vol.Marker:
    return vol.Required(key, default=current) if current else vol.Required(key)


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
    MINOR_VERSION = 2

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

    def _current(self, key: str, default: Any = None) -> Any:
        return self._pending.get(key, default)

    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(title="", data=self._pending)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select which currently implemented component is active."""
        if user_input is not None:
            self._pending.update(user_input)
            if not self._pending.get(CONF_ENERGY_FORECAST_ENABLED, False):
                return self._save()
            return await self.async_step_energy_forecast()

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
                return self._save()

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
                return self._save()

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
                return self._save()

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
