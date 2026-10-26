
"""DOEMS integration setup."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    ServiceCall,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    CONF_BATTERY_OBSERVATION_ENABLED,
    CONF_ANKER_OPERATING_MODE_ENTITY,
    CONF_ANKER_ACTION_DIRECTION_ENTITY,
    CONF_ANKER_POWER_SETPOINT_ENTITY,
    CONF_ENERGY_FORECAST_ENABLED,
    CONF_PRICES_ENABLED,
    DOMAIN,
    PLATFORMS,
)
from .automatic_combined_planner import DOEMSPlannerManager
from .combined_execution_shadow_runtime import DOEMSCombinedExecutionShadowRuntime
from .legacy_ems_safety import read_legacy_safety
from .automatic_slot_bridge import DOEMSAutoSlotBridge
from .r7_runtime import DOEMSR7Scheduler
from .battery_contract import DOEMSBatteryInputContract
from .energy_coordinator import DOEMSEnergyCoordinator
from .manual_plan_lifecycle import DOEMSManualPlanLifecycle
from .manual_plan_services import (
    async_register_manual_plan_services,
    async_unregister_manual_plan_services,
)
from .manual_plan_store import DOEMSManualPlanStore
from .manual_soc_projection import DOEMSManualSOCProjection
from .planner_migration import async_migrate_planner_architecture
from .prices_runtime import DOEMSRegisteredPricesManager
from .solar_actual import SolarActualQuarterManager
from .solar_forecast import SolarForecastManager
from .solar_foundation import SolarFoundationManager


type DOEMSConfigEntry = ConfigEntry

_LEGACY_SOLAR_FREEZE_STORAGE_VERSION = 1
_LEGACY_SOLAR_FREEZE_STORAGE_KEY = f"{DOMAIN}.solar_reference_freeze"

SERVICE_RESET_EMERGENCY_STATUS = "reset_emergency_status"


async def _async_remove_legacy_solar_freeze_storage(
    hass: HomeAssistant,
) -> None:
    """Remove the retired one-time Alpha41 Solar freeze store.

    The cleanup is intentionally idempotent so upgrades from releases
    that created the freeze store do not leave orphaned storage.
    """
    store: Store[dict] = Store(
        hass,
        _LEGACY_SOLAR_FREEZE_STORAGE_VERSION,
        _LEGACY_SOLAR_FREEZE_STORAGE_KEY,
    )
    await store.async_remove()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DOEMSConfigEntry,
) -> bool:
    """Set up DOEMS components from one config entry."""
    await _async_remove_legacy_solar_freeze_storage(hass)
    await async_migrate_planner_architecture(hass, entry)

    coordinator: DOEMSEnergyCoordinator | None = None
    if entry.options.get(CONF_ENERGY_FORECAST_ENABLED, False):
        coordinator = DOEMSEnergyCoordinator(hass, entry)
        await coordinator.async_setup()

    foundation = SolarFoundationManager(hass, entry)
    await foundation.async_setup()

    solar_forecast = SolarForecastManager(hass, foundation)
    await solar_forecast.async_setup()

    solar_actual = SolarActualQuarterManager(
        hass, foundation, solar_forecast
    )
    await solar_actual.async_setup()

    prices: DOEMSRegisteredPricesManager | None = None
    if entry.options.get(CONF_PRICES_ENABLED, False):
        prices = DOEMSRegisteredPricesManager(hass, entry)
        await prices.async_setup()

    battery_input: DOEMSBatteryInputContract | None = None
    if entry.options.get(CONF_BATTERY_OBSERVATION_ENABLED, False):
        battery_input = DOEMSBatteryInputContract(hass, entry)
        await battery_input.async_setup()

    manual_plan_store = DOEMSManualPlanStore(hass, entry.entry_id)
    await manual_plan_store.async_load()
    await async_register_manual_plan_services(
        hass, manual_plan_store
    )

    manual_plan_lifecycle = DOEMSManualPlanLifecycle(
        hass, manual_plan_store
    )
    await manual_plan_lifecycle.async_setup()

    manual_soc_projection = DOEMSManualSOCProjection(
        energy=coordinator,
        solar=solar_forecast,
        prices=prices,
        battery=battery_input,
        plans=manual_plan_store,
    )
    await manual_soc_projection.async_setup()

    planner = DOEMSPlannerManager(
        hass=hass,
        entry=entry,
        energy=coordinator,
        solar=solar_forecast,
        prices=prices,
        battery=battery_input,
        plans=manual_plan_store,
    )
    await planner.async_setup()

    r6_slot_bridge = DOEMSAutoSlotBridge(
        hass, planner, manual_plan_store
    )
    await r6_slot_bridge.async_setup()

    r7_scheduler = DOEMSR7Scheduler(
        hass,
        planner,
        r6_slot_bridge,
        manual_plan_store,
        battery_input,
    )
    await r7_scheduler.async_setup()

    combined_execution_shadow = DOEMSCombinedExecutionShadowRuntime(
        hass,
        r7_scheduler,
        manual_plan_store,
        planner=planner, battery=battery_input,
        entities={
            "operating_mode": entry.options.get(
                CONF_ANKER_OPERATING_MODE_ENTITY
            ),
            "action_direction": entry.options.get(
                CONF_ANKER_ACTION_DIRECTION_ENTITY
            ),
            "power_setpoint": entry.options.get(
                CONF_ANKER_POWER_SETPOINT_ENTITY
            ),
        },
    )
    await combined_execution_shadow.async_setup()

    entry.runtime_data = coordinator

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "energy_forecast_enabled": coordinator is not None,
        "solar_foundation": foundation,
        "solar_forecast": solar_forecast,
        "solar_actual": solar_actual,
        "prices": prices,
        "battery_input": battery_input,
        "manual_plan_store": manual_plan_store,
        "manual_plan_lifecycle": manual_plan_lifecycle,
        "manual_soc_projection": manual_soc_projection,
        "planner": planner,
        "r6_slot_bridge": r6_slot_bridge,
        "r7_scheduler": r7_scheduler,
        "combined_execution_shadow": combined_execution_shadow,
    }

    # Emergency acknowledgement service.
    #
    # This service must never issue physical battery commands.
    # The caller cannot supply safety flags or override safeguards.
    #
    # The required verified runtime sources for automatic arming
    # and physical-test activity are not yet connected.
    # Therefore the service remains fail-closed.

    async def _reset_emergency_status(
        call: ServiceCall,
    ) -> None:
        """Handle emergency acknowledgement without actuation."""
        runtime = hass.data.get(DOMAIN, {}).get(
            entry.entry_id
        )

        if runtime is None:
            raise HomeAssistantError(
                "Noodstopreset geblokkeerd: "
                "DOEMS-runtime ontbreekt"
            )

        execution = runtime.get(
            "combined_execution_shadow"
        )

        if not isinstance(
            execution,
            DOEMSCombinedExecutionShadowRuntime,
        ):
            raise HomeAssistantError(
                "Noodstopreset geblokkeerd: "
                "uitvoeringscontroller ontbreekt"
            )

        controller = execution.controller

        if (
            controller.session is not None
            or controller.reconciliation_required
        ):
            raise HomeAssistantError(
                "Noodstopreset geblokkeerd: "
                "uitvoering of reconciliatie actief"
            )

        # The old EMS is a separate controller. Read its live registered
        # arm, execution, physical-test and mode-switch states. An absent,
        # ambiguous or unavailable source must never permit acknowledgement.
        try:
            safety = read_legacy_safety(hass)
        except ValueError as err:
            raise HomeAssistantError(
                f"Noodstopreset geblokkeerd: {err}"
            ) from err

        await controller.async_reset_emergency_status(**safety)
        execution.refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_EMERGENCY_STATUS,
        _reset_emergency_status,
    )

    entry.async_on_unload(
        entry.add_update_listener(_async_update_listener)
    )

    await hass.config_entries.async_forward_entry_setups(
        entry, PLATFORMS
    )

    if (
        coordinator is not None
        and coordinator.source_entities
        and not coordinator.source_available
    ):
        remove_listener: Callable[[], None] | None = None

        @callback
        def _refresh_when_source_recovers(
            event: Event[EventStateChangedData],
        ) -> None:
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
            hass,
            coordinator.source_entities,
            _refresh_when_source_recovers,
        )

        entry.async_on_unload(
            _remove_recovery_listener
        )

        if coordinator.source_available:
            coordinator._notify()
            remove_listener()
            remove_listener = None

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: DOEMSConfigEntry,
) -> bool:
    coordinator = entry.runtime_data

    if isinstance(
        coordinator, DOEMSEnergyCoordinator
    ):
        await coordinator.async_shutdown()

    entry_data = hass.data.get(
        DOMAIN, {}
    ).get(entry.entry_id, {})

    prices = entry_data.get("prices")
    if isinstance(
        prices, DOEMSRegisteredPricesManager
    ):
        await prices.async_shutdown()

    battery_input = entry_data.get(
        "battery_input"
    )
    if isinstance(
        battery_input, DOEMSBatteryInputContract
    ):
        await battery_input.async_shutdown()

    combined_execution_shadow = entry_data.get(
        "combined_execution_shadow"
    )
    if isinstance(
        combined_execution_shadow,
        DOEMSCombinedExecutionShadowRuntime,
    ):
        await combined_execution_shadow.async_shutdown()

    r7_scheduler = entry_data.get(
        "r7_scheduler"
    )
    if isinstance(
        r7_scheduler, DOEMSR7Scheduler
    ):
        await r7_scheduler.async_shutdown()

    r6_slot_bridge = entry_data.get(
        "r6_slot_bridge"
    )
    if isinstance(
        r6_slot_bridge, DOEMSAutoSlotBridge
    ):
        await r6_slot_bridge.async_shutdown()

    manual_plan_lifecycle = entry_data.get(
        "manual_plan_lifecycle"
    )
    if isinstance(
        manual_plan_lifecycle,
        DOEMSManualPlanLifecycle,
    ):
        await manual_plan_lifecycle.async_shutdown()

    planner = entry_data.get("planner")
    if isinstance(
        planner, DOEMSPlannerManager
    ):
        await planner.async_shutdown()

    manual_soc_projection = entry_data.get(
        "manual_soc_projection"
    )
    if isinstance(
        manual_soc_projection,
        DOEMSManualSOCProjection,
    ):
        await manual_soc_projection.async_shutdown()

    solar_actual = entry_data.get(
        "solar_actual"
    )
    if isinstance(
        solar_actual, SolarActualQuarterManager
    ):
        await solar_actual.async_shutdown()

    solar_forecast = entry_data.get(
        "solar_forecast"
    )
    if isinstance(
        solar_forecast, SolarForecastManager
    ):
        await solar_forecast.async_shutdown()

    foundation = entry_data.get("solar_foundation")
    if isinstance(
        foundation, SolarFoundationManager
    ):
        await foundation.async_shutdown()

    unloaded = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )

    if unloaded:
        if hass.services.has_service(
            DOMAIN,
            SERVICE_RESET_EMERGENCY_STATUS,
        ):
            hass.services.async_remove(
                DOMAIN,
                SERVICE_RESET_EMERGENCY_STATUS,
            )

        await async_unregister_manual_plan_services(
            hass
        )

        hass.data.get(DOMAIN, {}).pop(
            entry.entry_id, None
        )
        entry.runtime_data = None

    return unloaded


async def _async_update_listener(
    hass: HomeAssistant,
    entry: DOEMSConfigEntry,
) -> None:
    await hass.config_entries.async_reload(
        entry.entry_id
    )

