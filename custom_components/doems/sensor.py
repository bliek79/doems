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
            "ems_enabled": False,
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
