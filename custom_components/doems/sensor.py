"""Public sensor entities for DOEMS."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EMS_ENABLED,
    CONF_ENERGY_FORECAST_ENABLED,
    CONF_INSTANCE_NAME,
    DEFAULT_INSTANCE_NAME,
    DEVICE_IDENTIFIER,
    DOMAIN,
    FORECAST_HORIZON_HOURS,
    FORECAST_SLOTS,
    FOUNDATION_PHASE,
    MAX_HISTORY_DAYS,
    NAME,
    PROFILE_LEARNING_OPTIONS,
    QUARTER_MINUTES,
    STORAGE_KEY,
    VERSION,
)
from .ems_settings import EMSSettings
from .ems_runtime import DOEMSEMSRuntime
from .ems_g5_live_parity_runtime import get_g5_live_parity_runtime
from .ems_g5_live_parity_sensor import DOEMSG5LiveParitySensor
from .energy_coordinator import DOEMSEnergyCoordinator
from .energy_forecast import EnergyBaselineForecast, ceil_quarter
from .prices import DOEMSPricesManager
from .presence import DOEMSPresenceStore
from .prices_sensor import build_prices_sensors
from .solar_forecast import SolarForecastManager
from .solar_sensor import build_solar_sensors

SUPPORTED_SOURCES = {"weekday_quarter", "day_type_quarter", "quarter_of_day"}


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
        name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
        manufacturer=NAME,
        model="Energy Management System",
        sw_version=VERSION,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DOEMS foundation, Energy, Solar and Prices sensors."""
    entities: list[SensorEntity] = [DOEMSFoundationStatusSensor(entry)]
    coordinator = entry.runtime_data
    if isinstance(coordinator, DOEMSEnergyCoordinator):
        entities.extend(
            [
                DOEMSSourceHomePowerSensor(entry, coordinator),
                DOEMSEnergyActualQuarterSensor(entry, coordinator),
                DOEMSEnergyHistoryStatusSensor(entry, coordinator),
                DOEMSEnergyHistoryDaysSensor(entry, coordinator),
                DOEMSEnergyForecastModelSensor(entry, coordinator),
                DOEMSEnergyForecastSensor(entry, coordinator),
                DOEMSEnergyForecastTimelineSensor(entry, coordinator),
                DOEMSEnergyForecastNextQuarterSensor(entry, coordinator),
                DOEMSEnergyForecastCoverageSensor(entry, coordinator),
                DOEMSEnergyForecastConfidenceSensor(entry, coordinator),
            ]
        )

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    presence = entry_data.get("presence")
    if isinstance(presence, DOEMSPresenceStore):
        entities.append(DOEMSPresenceContextSensor(entry, presence))

    ems_settings = entry_data.get("ems_settings")
    ems_runtime = entry_data.get("ems_runtime")
    if isinstance(ems_settings, EMSSettings):
        entities.append(
            DOEMSEMSSettingsSensor(
                entry,
                ems_settings,
                ems_runtime if isinstance(ems_runtime, DOEMSEMSRuntime) else None,
            )
        )
    if isinstance(ems_runtime, DOEMSEMSRuntime):
        entities.extend(
            [
                DOEMSEMSStatusSensor(entry, ems_runtime),
                *build_plan72_sensors(entry, ems_runtime),
                DOEMSSchedulerStatusSensor(entry, ems_runtime),
                *(DOEMSPlanStatusSensor(entry, ems_runtime, slot) for slot in range(1, 4)),
                DOEMSG5LiveParitySensor(
                    entry,
                    get_g5_live_parity_runtime(ems_runtime),
                ),
            ]
        )

    solar_forecast = entry_data.get("solar_forecast")
    if isinstance(solar_forecast, SolarForecastManager):
        entities.extend(build_solar_sensors(entry, solar_forecast))

    prices = entry_data.get("prices")
    if isinstance(prices, DOEMSPricesManager):
        entities.extend(build_prices_sensors(entry, prices))

    async_add_entities(entities)



class DOEMSPresenceContextSensor(SensorEntity):
    """Expose the shared DOEMS Presence/Away runtime context."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS Presence Context"
    _attr_unique_id = "doems_presence_context"
    _attr_suggested_object_id = "doems_presence_context"
    _attr_icon = "mdi:home-account"

    def __init__(self, entry: ConfigEntry, presence: DOEMSPresenceStore) -> None:
        self.presence = presence
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> str:
        return self.presence.effective_profile

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.presence.context()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.presence.async_add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class DOEMSEMSSettingsSensor(SensorEntity):
    """Expose the immutable Step-5A EMS settings snapshot for live validation."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS EMS Settings"
    _attr_unique_id = "doems_ems_settings"
    _attr_suggested_object_id = "doems_ems_settings"
    _attr_icon = "mdi:tune-variant"

    def __init__(
        self,
        entry: ConfigEntry,
        settings: EMSSettings,
        runtime: DOEMSEMSRuntime | None = None,
    ) -> None:
        self.settings = settings
        self.runtime = runtime
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> str:
        return "ready"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self.settings.as_contract(),
            "settings_source": "config_entry_options",
            "settings_snapshot_immutable": True,
            "startup_delay_runtime_gate_active": False,
            "planner_logic_active": self.runtime is not None,
            "planning_runtime_status": self.runtime.status if self.runtime is not None else None,
            "physical_execution_authority": False,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.runtime is not None:
            self._remove_listener = self.runtime.async_add_listener(self._handle_runtime_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_runtime_update(self) -> None:
        self.async_write_ha_state()


class DOEMSFoundationStatusSensor(SensorEntity):
    """Expose clean DOEMS identity, component and safety status."""

    _attr_has_entity_name = False
    _attr_name = "DOEMS Status"
    _attr_icon = "mdi:home-lightning-bolt-outline"
    _attr_unique_id = "doems_status"
    _attr_suggested_object_id = "doems_status"

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> str:
        return "ready"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        enabled = bool(self.entry.options.get(CONF_ENERGY_FORECAST_ENABLED, False))
        configured_fields = sum(
            1
            for key, value in self.entry.options.items()
            if key not in {CONF_INSTANCE_NAME, CONF_ENERGY_FORECAST_ENABLED}
            and value is not None
            and value != ""
        )
        return {
            "phase": FOUNDATION_PHASE,
            "domain": DOMAIN,
            "version": VERSION,
            "storage_namespace": DOMAIN,
            "energy_storage_key": STORAGE_KEY if enabled else None,
            "installation_required_input_count": configured_fields if enabled else 0,
            "forecast_enabled": enabled,
            "ems_enabled": bool(self.entry.options.get(CONF_EMS_ENABLED, False)),
            "physical_execution_authority": False,
            "identity_pure": True,
            "public_object_id_prefix": "doems_",
        }


class DOEMSEnergyBaseSensor(SensorEntity):
    """Base class for quarter-driven Energy Forecast sensors."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, entry: ConfigEntry, coordinator: DOEMSEnergyCoordinator) -> None:
        self.entry = entry
        self.coordinator = coordinator
        self._remove_listener = None
        self._forecast_cache_key: tuple[Any, ...] | None = None
        self._forecast_cache = None
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.coordinator.async_add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_update(self) -> None:
        self._forecast_cache_key = None
        self._forecast_cache = None
        self.async_write_ha_state()

    @property
    def _profile_learnable(self) -> bool:
        return self.coordinator.profile in PROFILE_LEARNING_OPTIONS

    def _forecast(self):
        reference = dt_util.utcnow()
        window_start = ceil_quarter(reference)
        key = (
            self.coordinator.profile,
            len(self.coordinator.records),
            window_start.isoformat(),
        )
        if key != self._forecast_cache_key:
            self._forecast_cache = self.coordinator.forecast(now=reference)
            self._forecast_cache_key = key
        return self._forecast_cache or []


class DOEMSSourceHomePowerSensor(SensorEntity):
    """Canonical public Home Power input consumed by the DOEMS forecast."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS Source Home Power"
    _attr_unique_id = "doems_source_home_power"
    _attr_suggested_object_id = "doems_source_home_power"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-lightning-bolt-outline"

    def __init__(self, entry: ConfigEntry, coordinator: DOEMSEnergyCoordinator) -> None:
        self.entry = entry
        self.coordinator = coordinator
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

    @property
    def available(self) -> bool:
        return self.coordinator.source_available

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.current_home_power_w
        return round(value, 3) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "source_mode": self.coordinator.source_mode,
            "source_entities": self.coordinator.source_entities,
            "source_available": self.coordinator.source_available,
            "normalization": "W/kW_to_W",
            "power_balance_formula": "solar + grid_import + battery_discharge - grid_export - battery_charge",
            "canonical_contract": "actual_home_load_w",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.source_entities:
            self._remove_listener = async_track_state_change_event(
                self.hass,
                self.coordinator.source_entities,
                self._handle_source_update,
            )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_source_update(self, event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()


class DOEMSEnergyActualQuarterSensor(DOEMSEnergyBaseSensor):
    _attr_name = "DOEMS Energy Actual Quarter"
    _attr_unique_id = "doems_energy_actual_quarter"
    _attr_suggested_object_id = "doems_energy_actual_quarter"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_icon = "mdi:home-lightning-bolt-outline"

    @property
    def native_value(self) -> float | None:
        result = self.coordinator.last_quarter
        return result.energy_kwh if result and result.measurement_valid else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self.coordinator.last_quarter
        if result is None:
            return {
                "resolution_minutes": QUARTER_MINUTES,
                "source_entity": self.coordinator.source_entity,
                "profile": self.coordinator.profile,
                "status": "waiting_for_first_quarter",
            }
        return {
            "resolution_minutes": QUARTER_MINUTES,
            "period_start": result.start.isoformat(),
            "period_end": result.end.isoformat(),
            "coverage": result.coverage,
            "measurement_valid": result.measurement_valid,
            "learning_valid": result.learning_valid,
            "learning_blocker": result.learning_blocker,
            "source_entity": self.coordinator.source_entity,
            "profile": result.profile,
        }


class DOEMSEnergyHistoryStatusSensor(DOEMSEnergyBaseSensor):
    _attr_name = "DOEMS Energy History Status"
    _attr_unique_id = "doems_energy_history_status"
    _attr_suggested_object_id = "doems_energy_history_status"
    _attr_icon = "mdi:database-check-outline"

    @property
    def native_value(self) -> str:
        if not self.coordinator.source_available:
            return "source_unavailable"
        if self.coordinator.valid_quarters == 0:
            return "collecting"
        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "source_entity": self.coordinator.source_entity,
            "source_mode": self.coordinator.source_mode,
            "source_available": self.coordinator.source_available,
            "valid_quarters": self.coordinator.valid_quarters,
            "history_days": self.coordinator.history_days,
            "profile": self.coordinator.profile,
            "storage_limit_days": MAX_HISTORY_DAYS,
            "storage_key": STORAGE_KEY,
            "history_reset_reason": self.coordinator.history_reset_reason,
            "profile_statistics": self.coordinator.profile_statistics(),
        }


class DOEMSEnergyHistoryDaysSensor(DOEMSEnergyBaseSensor):
    _attr_name = "DOEMS Energy History Days"
    _attr_unique_id = "doems_energy_history_days"
    _attr_suggested_object_id = "doems_energy_history_days"
    _attr_native_unit_of_measurement = "d"
    _attr_icon = "mdi:calendar-clock-outline"

    @property
    def native_value(self) -> int:
        return self.coordinator.history_days

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "valid_quarters": self.coordinator.valid_quarters,
            "resolution_minutes": QUARTER_MINUTES,
        }


class DOEMSEnergyForecastModelSensor(DOEMSEnergyBaseSensor):
    _attr_name = "DOEMS Energy Forecast Model"
    _attr_unique_id = "doems_energy_forecast_model"
    _attr_suggested_object_id = "doems_energy_forecast_model"
    _attr_icon = "mdi:chart-timeline-variant-shimmer"

    @property
    def native_value(self) -> str:
        return "historical_baseline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "model_version": "0.4",
            "forecast_active": self._profile_learnable,
            "recency_weighting_active": self._profile_learnable,
            "day_type_active": self._profile_learnable,
            "resolution_minutes": QUARTER_MINUTES,
            "horizon_hours": FORECAST_HORIZON_HOURS,
            "forecast_slots": FORECAST_SLOTS,
            "profile": self.coordinator.profile,
            "profile_statistics": self.coordinator.profile_statistics(),
            "alpha41_functional_parity_target": True,
        }


class DOEMSEnergyForecastSensor(DOEMSEnergyBaseSensor):
    _attr_name = "DOEMS Energy Forecast"
    _attr_unique_id = "doems_energy_forecast"
    _attr_suggested_object_id = "doems_energy_forecast"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_icon = "mdi:home-clock-outline"

    @property
    def native_value(self) -> float | None:
        values = [slot.energy_kwh for slot in self._forecast() if slot.energy_kwh is not None]
        return round(sum(values), 3) if values else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        slots = self._forecast()
        populated = sum(1 for slot in slots if slot.energy_kwh is not None)
        supported = sum(1 for slot in slots if slot.source in SUPPORTED_SOURCES)
        return {
            "status": "ok" if self._profile_learnable else "profile_unclassified",
            "profile": self.coordinator.profile,
            "model": "historical_baseline",
            "model_version": "0.4",
            "forecast_start": slots[0].start.isoformat() if slots else None,
            "resolution_minutes": QUARTER_MINUTES,
            "horizon_hours": FORECAST_HORIZON_HOURS,
            "slot_count": len(slots),
            "populated_slots": populated,
            "supported_slots": supported,
            "coverage_percent": round(supported / len(slots) * 100, 1) if slots else 0.0,
            "average_confidence_percent": EnergyBaselineForecast.average_confidence(slots),
            "timeline_entity": "sensor.doems_energy_forecast_timeline",
        }


class DOEMSEnergyForecastTimelineSensor(DOEMSEnergyBaseSensor):
    _attr_name = "DOEMS Energy Forecast Timeline"
    _attr_unique_id = "doems_energy_forecast_timeline"
    _attr_suggested_object_id = "doems_energy_forecast_timeline"
    _attr_icon = "mdi:chart-line"
    _unrecorded_attributes = frozenset({"points"})

    @property
    def native_value(self) -> int:
        return sum(1 for slot in self._forecast() if slot.energy_kwh is not None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        slots = self._forecast()
        points = [
            [int(slot.start.timestamp() * 1000), slot.energy_kwh]
            for slot in slots
            if slot.energy_kwh is not None
        ]
        return {
            "status": "ok" if self._profile_learnable else "profile_unclassified",
            "profile": self.coordinator.profile,
            "model": "historical_baseline",
            "model_version": "0.4",
            "resolution_minutes": QUARTER_MINUTES,
            "horizon_hours": FORECAST_HORIZON_HOURS,
            "slot_count": len(slots),
            "point_count": len(points),
            "point_format": "[unix_ms, kwh]",
            "forecast_start": slots[0].start.isoformat() if slots else None,
            "forecast_end": slots[-1].end.isoformat() if slots else None,
            "recorder_points": "excluded_by_local_recorder_glob",
            "points": points,
        }


class DOEMSEnergyForecastNextQuarterSensor(DOEMSEnergyBaseSensor):
    _attr_name = "DOEMS Energy Forecast Next Quarter"
    _attr_unique_id = "doems_energy_forecast_next_quarter"
    _attr_suggested_object_id = "doems_energy_forecast_next_quarter"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_icon = "mdi:clock-fast"

    @property
    def native_value(self) -> float | None:
        slots = self._forecast()
        return slots[0].energy_kwh if slots else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        slots = self._forecast()
        slot = slots[0] if slots else None
        return {
            "profile": self.coordinator.profile,
            "start": slot.start.isoformat() if slot else None,
            "end": slot.end.isoformat() if slot else None,
            "sample_count": slot.sample_count if slot else 0,
            "source": slot.source if slot else None,
            "confidence": slot.confidence if slot else 0.0,
        }


class DOEMSEnergyForecastCoverageSensor(DOEMSEnergyBaseSensor):
    _attr_name = "DOEMS Energy Forecast Coverage"
    _attr_unique_id = "doems_energy_forecast_coverage"
    _attr_suggested_object_id = "doems_energy_forecast_coverage"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:chart-donut"

    @property
    def native_value(self) -> float:
        slots = self._forecast()
        if not slots:
            return 0.0
        supported = sum(1 for slot in slots if slot.source in SUPPORTED_SOURCES)
        return round(supported / len(slots) * 100.0, 1)


class DOEMSEnergyForecastConfidenceSensor(DOEMSEnergyBaseSensor):
    _attr_name = "DOEMS Energy Forecast Confidence"
    _attr_unique_id = "doems_energy_forecast_confidence"
    _attr_suggested_object_id = "doems_energy_forecast_confidence"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:shield-check-outline"

    @property
    def native_value(self) -> float | None:
        return EnergyBaselineForecast.average_confidence(self._forecast())



class _DOEMSEMSRuntimeSensor(SensorEntity):
    """Base entity for the definitive Alpha8 DOEMS EMS runtime."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, entry: ConfigEntry, runtime: DOEMSEMSRuntime) -> None:
        self.runtime = runtime
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.runtime.async_add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class DOEMSEMSStatusSensor(_DOEMSEMSRuntimeSensor):
    """Central non-actuating DOEMS EMS status."""

    _unrecorded_attributes = frozenset({
        "auto_final_revalidation_checks",
        "auto_mode_switch_preview_transaction",
        "auto_execution_gate_checks",
        "execution_shadow_transaction",
        "runtime_safety_checks",
        "safe_return_steps",
        "execution_shadow_trace",
        "execution_shadow_run_history",
    })
    _attr_name = "DOEMS EMS"
    _attr_unique_id = "doems_ems"
    _attr_suggested_object_id = "doems_ems"
    _attr_icon = "mdi:home-lightning-bolt"

    @property
    def native_value(self) -> str:
        return self.runtime.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.runtime.snapshot()



def _plan72_summary_attrs(data: dict[str, Any]) -> dict[str, Any]:
    """Source-parity public Plan72 summary attributes."""
    return {
        "valid": data.get("auto_plan_72h_valid", False),
        "reason": data.get("auto_plan_72h_reason"),
        "count": data.get("auto_plan_72h_count"),
        "start": data.get("auto_plan_72h_start"),
        "end": data.get("auto_plan_72h_end"),
        "start_soc": data.get("auto_plan_72h_start_soc"),
        "end_soc": data.get("auto_plan_72h_end_soc"),
        "min_soc": data.get("auto_plan_72h_min_soc"),
        "max_soc": data.get("auto_plan_72h_max_soc"),
        "reserve_floor_soc": data.get("auto_plan_72h_reserve_floor_soc"),
        "dynamic_reserve_min_soc": data.get("auto_plan_72h_dynamic_reserve_min_soc"),
        "dynamic_reserve_max_soc": data.get("auto_plan_72h_dynamic_reserve_max_soc"),
        "execution_buffer_percent": data.get("auto_plan_72h_execution_buffer_percent"),
        "max_charge_power_w": data.get("auto_plan_72h_max_charge_power_w"),
        "max_discharge_power_w": data.get("auto_plan_72h_max_discharge_power_w"),
        "execution_reserve_floor_soc": data.get("auto_plan_72h_execution_reserve_floor_soc"),
        "execution_reserve_min_soc": data.get("auto_plan_72h_execution_reserve_min_soc"),
        "execution_reserve_max_soc": data.get("auto_plan_72h_execution_reserve_max_soc"),
        "min_execution_headroom_soc": data.get("auto_plan_72h_min_execution_headroom_soc"),
        "execution_buffer_breach_hours": data.get("auto_plan_72h_execution_buffer_breach_hours"),
        "execution_buffer_safe": data.get("auto_plan_72h_execution_buffer_safe", False),
        "solar_horizon_complete": data.get("auto_plan_72h_solar_horizon_complete"),
        "solar_horizon_incomplete_hours": data.get("auto_plan_72h_solar_horizon_incomplete_hours"),
        "solar_charge_kwh": data.get("auto_plan_72h_solar_charge_kwh"),
        "grid_safety_charge_kwh": data.get("auto_plan_72h_grid_safety_charge_kwh"),
        "grid_support_charge_kwh": data.get("auto_plan_72h_grid_support_charge_kwh"),
        "grid_trade_charge_kwh": data.get("auto_plan_72h_grid_trade_charge_kwh"),
        "home_discharge_kwh": data.get("auto_plan_72h_home_discharge_kwh"),
        "grid_trade_discharge_kwh": data.get("auto_plan_72h_grid_trade_discharge_kwh"),
        "grid_import_for_home_kwh": data.get("auto_plan_72h_grid_import_for_home_kwh"),
        "solar_export_kwh": data.get("auto_plan_72h_solar_export_kwh"),
        "charge_efficiency_percent": data.get("auto_plan_72h_charge_efficiency_percent"),
        "discharge_efficiency_percent": data.get("auto_plan_72h_discharge_efficiency_percent"),
        "observational_only": data.get("auto_plan_72h_observational_only", True),
        "execution_enabled": data.get("auto_plan_72h_execution_enabled", False),
        "note": data.get("auto_plan_72h_note"),
    }


class DOEMSEMSPlan72Sensor(_DOEMSEMSRuntimeSensor):
    """Expose the existing Plan72 calculation with source-parity observability."""

    _attr_icon = "mdi:chart-timeline-variant-shimmer"

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: DOEMSEMSRuntime,
        *,
        suffix: str,
        name: str,
        value_key: str | None = None,
        unit: str | None = None,
        include_plan: bool = False,
        solar_horizon_status: bool = False,
    ) -> None:
        super().__init__(entry, runtime)
        self._suffix = suffix
        self._value_key = value_key
        self._include_plan = include_plan
        self._solar_horizon_status = solar_horizon_status
        self._attr_name = name
        self._attr_unique_id = f"doems_ems_plan72_{suffix}"
        self._attr_suggested_object_id = f"doems_ems_plan72_{suffix}"
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if include_plan:
            self._unrecorded_attributes = frozenset({"plan"})

    def _data(self) -> dict[str, Any]:
        planner = self.runtime.planner_result or {}
        return dict(planner.get("plan72") or {})

    @property
    def native_value(self) -> Any:
        data = self._data()
        if self._solar_horizon_status:
            return data.get("auto_plan_72h_solar_horizon_status") or "no_data"
        return data.get(self._value_key) if self._value_key else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._data()
        if self._solar_horizon_status:
            return {
                "forecast_coverage_hours": data.get(
                    "auto_plan_72h_solar_forecast_coverage_hours"
                ),
                "forecast_missing_hours": data.get(
                    "auto_plan_72h_solar_forecast_missing_hours"
                ),
                "forecast_coverage_percent": data.get(
                    "auto_plan_72h_solar_forecast_coverage_percent"
                ),
                "forecast_complete": data.get(
                    "auto_plan_72h_solar_forecast_complete", False
                ),
                "next_usable_solar_available": data.get(
                    "auto_plan_72h_next_usable_solar_available", False
                ),
                "next_usable_solar": data.get(
                    "auto_plan_72h_next_usable_solar"
                ),
                "hours_until_next_usable_solar": data.get(
                    "auto_plan_72h_hours_until_next_usable_solar"
                ),
                "last_usable_solar": data.get(
                    "auto_plan_72h_last_usable_solar"
                ),
                "plan_start": data.get("auto_plan_72h_start"),
                "plan_end": data.get("auto_plan_72h_end"),
                "hours_after_last_usable_solar": data.get(
                    "auto_plan_72h_hours_after_last_usable_solar"
                ),
                "lookahead_limited_by_plan_end": data.get(
                    "auto_plan_72h_lookahead_limited_by_plan_end", False
                ),
                "reason": data.get("auto_plan_72h_solar_horizon_reason"),
                "observational_only": data.get(
                    "auto_plan_72h_observational_only", True
                ),
            }

        attrs = _plan72_summary_attrs(data)
        if self._include_plan:
            attrs["plan"] = data.get("auto_plan_72h_plan", [])
        return attrs


def build_plan72_sensors(
    entry: ConfigEntry,
    runtime: DOEMSEMSRuntime,
) -> list[SensorEntity]:
    """Build the Plan72 public sensor set copied from the working source."""
    specs = [
        ("status", "DOEMS EMS Plan72 Status", "auto_plan_72h_status", None, False, False),
        ("hours", "DOEMS EMS Plan72 Hours", "auto_plan_72h_count", "h", True, False),
        ("end_soc", "DOEMS EMS Plan72 End SOC", "auto_plan_72h_end_soc", PERCENTAGE, False, False),
        ("min_soc", "DOEMS EMS Plan72 Minimum SOC", "auto_plan_72h_min_soc", PERCENTAGE, False, False),
        ("dynamic_reserve_now", "DOEMS EMS Plan72 Reserve", "auto_plan_72h_reserve_floor_soc", PERCENTAGE, False, False),
        ("dynamic_reserve_max", "DOEMS EMS Plan72 Maximum Reserve", "auto_plan_72h_dynamic_reserve_max_soc", PERCENTAGE, False, False),
        ("execution_reserve_now", "DOEMS EMS Plan72 Execution Reserve", "auto_plan_72h_execution_reserve_floor_soc", PERCENTAGE, False, False),
        ("execution_headroom_min", "DOEMS EMS Plan72 Execution Margin", "auto_plan_72h_min_execution_headroom_soc", PERCENTAGE, False, False),
        ("execution_buffer_breach_hours", "DOEMS EMS Plan72 Buffer Breach", "auto_plan_72h_execution_buffer_breach_hours", "h", False, False),
        ("solar_horizon_status", "DOEMS EMS Plan72 Solar Horizon", None, None, False, True),
        ("solar_horizon_incomplete_hours", "DOEMS EMS Plan72 Missing Solar Hours", "auto_plan_72h_solar_horizon_incomplete_hours", "h", False, False),
        ("solar_charge", "DOEMS EMS Plan72 Solar Charge", "auto_plan_72h_solar_charge_kwh", UnitOfEnergy.KILO_WATT_HOUR, False, False),
        ("grid_safety_charge", "DOEMS EMS Plan72 Safety Charge", "auto_plan_72h_grid_safety_charge_kwh", UnitOfEnergy.KILO_WATT_HOUR, False, False),
        ("grid_support_charge", "DOEMS EMS Plan72 Self-Consumption Support Charge", "auto_plan_72h_grid_support_charge_kwh", UnitOfEnergy.KILO_WATT_HOUR, False, False),
        ("grid_trade_charge", "DOEMS EMS Plan72 Trade Charge", "auto_plan_72h_grid_trade_charge_kwh", UnitOfEnergy.KILO_WATT_HOUR, False, False),
        ("home_discharge", "DOEMS EMS Plan72 Home Discharge", "auto_plan_72h_home_discharge_kwh", UnitOfEnergy.KILO_WATT_HOUR, False, False),
        ("grid_trade_discharge", "DOEMS EMS Plan72 Grid Discharge", "auto_plan_72h_grid_trade_discharge_kwh", UnitOfEnergy.KILO_WATT_HOUR, False, False),
    ]
    return [
        DOEMSEMSPlan72Sensor(
            entry,
            runtime,
            suffix=suffix,
            name=name,
            value_key=value_key,
            unit=unit,
            include_plan=include_plan,
            solar_horizon_status=solar_horizon_status,
        )
        for suffix, name, value_key, unit, include_plan, solar_horizon_status in specs
    ]


class DOEMSSchedulerStatusSensor(_DOEMSEMSRuntimeSensor):
    """Central definitive DOEMS Scheduler status."""

    _attr_name = "DOEMS Scheduler"
    _attr_unique_id = "doems_scheduler"
    _attr_suggested_object_id = "doems_scheduler"
    _attr_icon = "mdi:calendar-clock"

    @property
    def native_value(self) -> str:
        return str((self.runtime.scheduler_result or {}).get("scheduler_status") or "idle")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        scheduler = self.runtime.scheduler_result or {}
        return {
            "selected_slot": scheduler.get("scheduler_selected_slot"),
            "selected_action": scheduler.get("scheduler_selected_action"),
            "selected_execution_mode": scheduler.get("scheduler_selected_execution_mode"),
            "selected_start_time": scheduler.get("scheduler_selected_start_time"),
            "next_future_slot": scheduler.get("scheduler_next_future_slot"),
            "next_future_start": scheduler.get("scheduler_next_future_start"),
            "ready": bool(scheduler.get("scheduler_ready")),
            "physical_control": False,
            "mode": "validation",
        }


class DOEMSPlanStatusSensor(_DOEMSEMSRuntimeSensor):
    """Status of one definitive persistent DOEMS plan slot."""

    def __init__(self, entry: ConfigEntry, runtime: DOEMSEMSRuntime, slot: int) -> None:
        super().__init__(entry, runtime)
        self.slot = slot
        self._attr_name = f"DOEMS Plan {slot} Status"
        self._attr_unique_id = f"doems_plan_{slot}_status"
        self._attr_suggested_object_id = f"doems_plan_{slot}_status"
        self._attr_icon = "mdi:clipboard-text-clock-outline"

    def _detail(self) -> dict[str, Any]:
        scheduler = self.runtime.scheduler_result or {}
        slots = scheduler.get("scheduler_slots") or {}
        detail = slots.get(self.slot) or slots.get(str(self.slot))
        if isinstance(detail, dict):
            return dict(detail)
        plan = self.runtime.plan_store.get_plan(self.slot)
        return {
            **plan,
            "slot": self.slot,
            "status": self.runtime.plan_store.plan_status(self.slot),
            "selected": False,
            "physical_control": False,
        }

    @property
    def native_value(self) -> str:
        return str(self._detail().get("status") or "leeg")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        detail = self._detail()
        return {
            "slot": self.slot,
            "action": detail.get("action"),
            "execution_mode": detail.get("execution_mode"),
            "start_time": detail.get("start_time"),
            "start_window_end": detail.get("start_window_end"),
            "power_w": detail.get("power_w"),
            "target_soc": detail.get("target_soc"),
            "max_runtime_h": detail.get("max_runtime_h"),
            "max_start_delay_min": detail.get("max_start_delay_min"),
            "planned_energy_kwh": detail.get("planned_energy_kwh"),
            "planned_end_time": detail.get("planned_end_time"),
            "lifecycle_status": detail.get("lifecycle_status"),
            "lifecycle_reason": detail.get("lifecycle_reason"),
            "origin": detail.get("origin"),
            "purpose": detail.get("purpose"),
            "planner_identity": detail.get("planner_identity"),
            "planner_signature": detail.get("planner_signature"),
            "selected": bool(detail.get("selected")),
            "physical_control": False,
            "mode": "validation",
        }
