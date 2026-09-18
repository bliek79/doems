"""DOEMS integration setup."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import CONF_ENERGY_FORECAST_ENABLED, CONF_PRICES_ENABLED, DOMAIN, PLATFORMS
from .energy_coordinator import DOEMSEnergyCoordinator
from .prices_runtime import DOEMSRegisteredPricesManager
from .solar_forecast import SolarForecastManager
from .solar_foundation import SolarFoundationManager


type DOEMSConfigEntry = ConfigEntry

_LEGACY_SOLAR_FREEZE_STORAGE_VERSION = 1
_LEGACY_SOLAR_FREEZE_STORAGE_KEY = f"{DOMAIN}.solar_reference_freeze"


async def _async_remove_legacy_solar_freeze_storage(hass: HomeAssistant) -> None:
    """Remove the retired one-time Alpha41 Solar freeze store.

    The cleanup is intentionally idempotent so upgrades from releases that
    created the freeze store do not leave orphaned component-owned storage.
    """
    store: Store[dict] = Store(
        hass,
        _LEGACY_SOLAR_FREEZE_STORAGE_VERSION,
        _LEGACY_SOLAR_FREEZE_STORAGE_KEY,
    )
    await store.async_remove()


async def async_setup_entry(hass: HomeAssistant, entry: DOEMSConfigEntry) -> bool:
    """Set up DOEMS components from one config entry."""
    await _async_remove_legacy_solar_freeze_storage(hass)

    coordinator: DOEMSEnergyCoordinator | None = None
    if entry.options.get(CONF_ENERGY_FORECAST_ENABLED, False):
        coordinator = DOEMSEnergyCoordinator(hass, entry)
        await coordinator.async_setup()

    foundation = SolarFoundationManager(hass, entry)
    await foundation.async_setup()
    solar_forecast = SolarForecastManager(hass, foundation)
    await solar_forecast.async_setup()

    prices: DOEMSRegisteredPricesManager | None = None
    if entry.options.get(CONF_PRICES_ENABLED, False):
        prices = DOEMSRegisteredPricesManager(hass, entry)
        await prices.async_setup()

    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "energy_forecast_enabled": coordinator is not None,
        "solar_foundation": foundation,
        "solar_forecast": solar_forecast,
        "prices": prices,
    }
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if coordinator is not None and coordinator.source_entities and not coordinator.source_available:
        remove_listener: Callable[[], None] | None = None

        @callback
        def _refresh_when_source_recovers(event: Event[EventStateChangedData]) -> None:
            nonlocal remove_listener
            if not coordinator.source_available:
                return
            coordinator._notify()
            if remove_listener is not None:
                remove_listener()
                remove_listener = None

        @callback
        def _remove_recovery_listener() -> None:
            nonlocal remove_listener
            if remove_listener is not None:
                remove_listener()
                remove_listener = None

        remove_listener = async_track_state_change_event(
            hass, coordinator.source_entities, _refresh_when_source_recovers
        )
        entry.async_on_unload(_remove_recovery_listener)
        if coordinator.source_available:
            coordinator._notify()
            remove_listener()
            remove_listener = None

    return True


async def async_unload_entry(hass: HomeAssistant, entry: DOEMSConfigEntry) -> bool:
    coordinator = entry.runtime_data
    if isinstance(coordinator, DOEMSEnergyCoordinator):
        await coordinator.async_shutdown()

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    prices = entry_data.get("prices")
    if isinstance(prices, DOEMSRegisteredPricesManager):
        await prices.async_shutdown()

    solar_forecast = entry_data.get("solar_forecast")
    if isinstance(solar_forecast, SolarForecastManager):
        await solar_forecast.async_shutdown()

    foundation = entry_data.get("solar_foundation")
    if isinstance(foundation, SolarFoundationManager):
        await foundation.async_shutdown()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        entry.runtime_data = None
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: DOEMSConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
