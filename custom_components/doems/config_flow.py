"""Config flow for DOEMS."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .const import CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME, DOMAIN, NAME


class DOEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DOEMS."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the clean DOEMS config entry.

        Step 0 deliberately requires no installation-specific data. Future
        component steps add only the inputs that component actually needs.
        """
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return DOEMSOptionsFlow(config_entry)


class DOEMSOptionsFlow(OptionsFlow):
    """Handle optional DOEMS settings."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage optional foundation settings."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_name = self._config_entry.options.get(
            CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_INSTANCE_NAME,
                        default=current_name,
                    ): str,
                }
            ),
        )
