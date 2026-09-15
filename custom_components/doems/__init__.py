"""DOEMS integration foundation."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS


type DOEMSConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: DOEMSConfigEntry) -> bool:
    """Set up DOEMS from a config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DOEMSConfigEntry) -> bool:
    """Unload a DOEMS config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: DOEMSConfigEntry) -> None:
    """Reload DOEMS after options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)
