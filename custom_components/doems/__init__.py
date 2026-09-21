"""DOEMS integration setup."""

from __future__ import annotations

from collections.abc import Callable

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EMS_ENABLED,
    CONF_ENERGY_FORECAST_ENABLED,
    CONF_PRICES_ENABLED,
    DOMAIN,
    PLATFORMS,
    PLAN_SLOT_COUNT,
    SERVICE_CANCEL_PLAN,
    SERVICE_SCHEDULE_PLAN,
)
from .ems_settings import EMSSettings
from .ems_runtime import DOEMSEMSRuntime
from .energy_coordinator import DOEMSEnergyCoordinator
from .prices_runtime import DOEMSRegisteredPricesManager
from .presence import DOEMSPresenceStore
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


def _single_ems_runtime(hass: HomeAssistant) -> DOEMSEMSRuntime:
    """Return the single active DOEMS EMS runtime."""
    runtimes = []
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if not isinstance(entry_data, dict):
            continue
        runtime = entry_data.get("ems_runtime")
        if isinstance(runtime, DOEMSEMSRuntime):
            runtimes.append(runtime)
    if len(runtimes) != 1:
        raise HomeAssistantError(
            "DOEMS-planbediening vereist precies één geladen EMS-runtime"
        )
    return runtimes[0]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register non-actuating Alpha8 manual plan lifecycle services."""

    def _slot_from_call(call: ServiceCall) -> int:
        slot = int(call.data.get("slot", 0))
        if slot not in range(1, PLAN_SLOT_COUNT + 1):
            raise HomeAssistantError("Planplaats moet 1, 2 of 3 zijn")
        return slot

    async def _schedule_plan(call: ServiceCall) -> None:
        runtime = _single_ems_runtime(hass)
        slot = _slot_from_call(call)
        current = runtime.plan_store.get_plan(slot)
        if current.get("action") == "geen":
            raise HomeAssistantError(f"Plan {slot} heeft nog geen actie")
        start_raw = current.get("start_time")
        start = dt_util.parse_datetime(str(start_raw)) if start_raw else None
        if start is None:
            raise HomeAssistantError(f"Plan {slot} heeft geen geldige starttijd")
        if start.tzinfo is None:
            start = start.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        if start <= dt_util.now():
            raise HomeAssistantError(f"Plan {slot} starttijd moet in de toekomst liggen")

        await runtime.plan_store.async_set_value(slot, "execution_mode", "gepland")
        await runtime.plan_store.async_mark_lifecycle(
            slot, "pending", "scheduled_by_user"
        )
        await runtime.async_refresh("manual_schedule_plan")

    async def _cancel_plan(call: ServiceCall) -> None:
        runtime = _single_ems_runtime(hass)
        slot = _slot_from_call(call)
        await runtime.plan_store.async_mark_lifecycle(
            slot, "geannuleerd", "manual_cancel"
        )
        await runtime.async_refresh("manual_cancel_plan")

    slot_schema = vol.All(vol.Coerce(int), vol.Range(min=1, max=PLAN_SLOT_COUNT))
    hass.services.async_register(
        DOMAIN,
        SERVICE_SCHEDULE_PLAN,
        _schedule_plan,
        schema=vol.Schema({vol.Required("slot"): slot_schema}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_PLAN,
        _cancel_plan,
        schema=vol.Schema({vol.Required("slot"): slot_schema}),
    )
    return True


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

    presence = DOEMSPresenceStore(hass, entry, coordinator)
    await presence.async_setup()

    ems_settings = (
        EMSSettings.from_options(entry.options)
        if entry.options.get(CONF_EMS_ENABLED, False)
        else None
    )

    ems_runtime = None
    if ems_settings is not None:
        ems_runtime = DOEMSEMSRuntime(
            hass,
            entry,
            ems_settings,
            coordinator,
            solar_forecast,
            prices,
        )
        await ems_runtime.async_setup()

    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "energy_forecast_enabled": coordinator is not None,
        "solar_foundation": foundation,
        "solar_forecast": solar_forecast,
        "prices": prices,
        "presence": presence,
        "ems_settings": ems_settings,
        "ems_runtime": ems_runtime,
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
    ems_runtime = entry_data.get("ems_runtime")
    if isinstance(ems_runtime, DOEMSEMSRuntime):
        await ems_runtime.async_shutdown()

    presence = entry_data.get("presence")
    if isinstance(presence, DOEMSPresenceStore):
        await presence.async_shutdown()

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
