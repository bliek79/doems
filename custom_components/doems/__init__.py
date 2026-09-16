"""DOEMS integration setup."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_ENERGY_FORECAST_ENABLED, DOMAIN, PLATFORMS
from .energy_coordinator import DOEMSEnergyCoordinator
from .solar_reference_freeze_runtime import SolarReferenceFreezeManager


type DOEMSConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: DOEMSConfigEntry) -> bool:
    """Set up the clean DOEMS integration from a config entry."""
    coordinator: DOEMSEnergyCoordinator | None = None
    if entry.options.get(CONF_ENERGY_FORECAST_ENABLED, False):
        coordinator = DOEMSEnergyCoordinator(hass, entry)
        await coordinator.async_setup()

    freeze_manager = SolarReferenceFreezeManager(hass)
    await freeze_manager.async_setup()

    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "energy_forecast_enabled": coordinator is not None,
        "solar_reference_freeze": freeze_manager,
    }
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # During a Home Assistant restart, DOEMS can finish setup before all selected
    # power-source entities are restored. Energy History Status then correctly
    # starts as source_unavailable, but Alpha2 only refreshed quarter-driven
    # diagnostics at the next 15-minute boundary. Subscribe once while the source
    # is unavailable and refresh the diagnostics immediately when the complete
    # canonical Home Power source becomes available again.
    if coordinator is not None and coordinator.source_entities and not coordinator.source_available:
        remove_listener: Callable[[], None] | None = None

        @callback
        def _refresh_when_source_recovers(event: Event[EventStateChangedData]) -> None:
            """Refresh quarter-driven diagnostics once the full source recovers."""
            nonlocal remove_listener
            if not coordinator.source_available:
                return
            coordinator._notify()
            if remove_listener is not None:
                remove_listener()
                remove_listener = None

        @callback
        def _remove_recovery_listener() -> None:
            """Remove the temporary recovery listener when the entry unloads."""
            nonlocal remove_listener
            if remove_listener is not None:
                remove_listener()
                remove_listener = None

        remove_listener = async_track_state_change_event(
            hass,
            coordinator.source_entities,
            _refresh_when_source_recovers,
        )
        entry.async_on_unload(_remove_recovery_listener)

        # Close the small race where the source recovers between the check above
        # and registering the state-change listener.
        if coordinator.source_available:
            coordinator._notify()
            remove_listener()
            remove_listener = None

    return True


async def async_unload_entry(hass: HomeAssistant, entry: DOEMSConfigEntry) -> bool:
    """Unload DOEMS and persist component-owned state."""
    coordinator = entry.runtime_data
    if isinstance(coordinator, DOEMSEnergyCoordinator):
        await coordinator.async_shutdown()

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    freeze_manager = entry_data.get("solar_reference_freeze")
    if isinstance(freeze_manager, SolarReferenceFreezeManager):
        await freeze_manager.async_shutdown()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        entry.runtime_data = None
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: DOEMSConfigEntry) -> None:
    """Reload DOEMS after options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)
