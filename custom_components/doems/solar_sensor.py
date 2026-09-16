"""Public Home Assistant sensors for DOEMS Solar P3.1."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import (
    CONF_INSTANCE_NAME,
    DEFAULT_INSTANCE_NAME,
    DEVICE_IDENTIFIER,
    DOMAIN,
    NAME,
    VERSION,
)
from .solar_forecast import OPEN_METEO_SOLAR_ENDPOINT, SolarForecastManager
from .solar_forecast_model import (
    SOLAR_FORECAST_MODEL,
    SOLAR_FORECAST_SLOTS,
    SOLAR_HORIZON_HOURS,
    SOLAR_RESOLUTION_MINUTES,
)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
        name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
        manufacturer=NAME,
        model="Energy Management System",
        sw_version=VERSION,
    )


def build_solar_sensors(
    entry: ConfigEntry,
    manager: SolarForecastManager,
) -> list[SensorEntity]:
    """Build the public provider-neutral Solar P3.1 sensor contract."""
    return [
        DOEMSSolarSourceStatusSensor(entry, manager),
        DOEMSSolarForecastTimelineSensor(entry, manager),
        DOEMSSolarForecastNextQuarterSensor(entry, manager),
        DOEMSSolarForecastDailySensor(entry, manager, "today"),
        DOEMSSolarForecastDailySensor(entry, manager, "tomorrow"),
        DOEMSSolarForecastModelSensor(entry, manager),
    ]


class DOEMSSolarBaseSensor(SensorEntity):
    """Base class for push-updated Solar P3.1 entities."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, entry: ConfigEntry, manager: SolarForecastManager) -> None:
        self.manager = manager
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.manager.async_add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class DOEMSSolarSourceStatusSensor(DOEMSSolarBaseSensor):
    """Expose provider freshness and runtime diagnostics."""

    _attr_name = "DOEMS Solar Source Status"
    _attr_unique_id = "doems_solar_source_status"
    _attr_suggested_object_id = "doems_solar_source_status"
    _attr_icon = "mdi:solar-power-variant-outline"

    @property
    def native_value(self) -> str:
        return self.manager.source_status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        contract = self.manager.contract
        return {
            "provider": "Open-Meteo",
            "attribution": "Weather data by Open-Meteo.com",
            "endpoint": OPEN_METEO_SOLAR_ENDPOINT,
            "last_attempt": (
                self.manager.last_attempt.isoformat()
                if self.manager.last_attempt is not None
                else None
            ),
            "last_successful_update": (
                self.manager.last_successful_update.isoformat()
                if self.manager.last_successful_update is not None
                else None
            ),
            "age_minutes": self.manager.age_minutes,
            "last_error": self.manager.last_error,
            "point_count": len(self.manager.points),
            "source_buffer_point_count": self.manager.source_point_count,
            "refresh_schedule": "hourly at :00:20",
            "retry_backoff_seconds": [0, 5, 15],
            "foundation_status": self.manager.foundation.status,
            "forecast_runtime_active": self.manager.foundation.forecast_runtime_active,
            "topology_signature": contract.get("topology_signature"),
            "location_source": contract.get("location_source"),
            "latitude": contract.get("latitude"),
            "longitude": contract.get("longitude"),
            "array_ids": contract.get("array_ids", []),
            "physical_execution_authority": False,
        }


class DOEMSSolarForecastTimelineSensor(DOEMSSolarBaseSensor):
    """Expose the canonical generic 288-slot Solar timeline."""

    _attr_name = "DOEMS Solar Forecast Timeline"
    _attr_unique_id = "doems_solar_forecast_timeline"
    _attr_suggested_object_id = "doems_solar_forecast_timeline"
    _attr_icon = "mdi:chart-timeline-variant-shimmer"
    _unrecorded_attributes = frozenset({"points"})

    @property
    def native_value(self) -> int:
        return len(self.manager.points)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        points = self.manager.points
        contract = self.manager.contract
        return {
            "status": self.manager.source_status,
            "source": "open_meteo",
            "model": SOLAR_FORECAST_MODEL,
            "resolution_minutes": SOLAR_RESOLUTION_MINUTES,
            "horizon_hours": SOLAR_HORIZON_HOURS,
            "slot_count": SOLAR_FORECAST_SLOTS,
            "point_count": len(points),
            "source_buffer_point_count": self.manager.source_point_count,
            "array_ids": contract.get("array_ids", []),
            "array_names": contract.get("array_names", []),
            "point_format": "[unix_ms,total_kwh,total_kw,array_kwh[],array_kw[],array_gti_wm2[]]",
            "array_value_order": "array_ids",
            "interval_semantics": "slot_start; Open-Meteo backward-average timestamp shifted by 15 minutes",
            "forecast_start": points[0].start.isoformat() if points else None,
            "last_slot_start": points[-1].start.isoformat() if points else None,
            "forecast_end": (
                (points[-1].start + timedelta(minutes=SOLAR_RESOLUTION_MINUTES)).isoformat()
                if points
                else None
            ),
            "topology_signature": contract.get("topology_signature"),
            "recorder_points": "excluded",
            "points": [point.as_list() for point in points],
        }


class DOEMSSolarForecastNextQuarterSensor(DOEMSSolarBaseSensor):
    """Expose the first future Solar slot in the rolling contract."""

    _attr_name = "DOEMS Solar Forecast Next Quarter"
    _attr_unique_id = "doems_solar_forecast_next_quarter"
    _attr_suggested_object_id = "doems_solar_forecast_next_quarter"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_icon = "mdi:solar-power-variant"

    @property
    def native_value(self) -> float | None:
        point = self.manager.next_quarter_point()
        return point.total_kwh if point is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        point = self.manager.next_quarter_point()
        contract = self.manager.contract
        return {
            "status": self.manager.source_status,
            "start": point.start.isoformat() if point is not None else None,
            "end": (
                (point.start + timedelta(minutes=SOLAR_RESOLUTION_MINUTES)).isoformat()
                if point is not None
                else None
            ),
            "total_kw": point.total_kw if point is not None else None,
            "array_ids": contract.get("array_ids", []),
            "array_names": contract.get("array_names", []),
            "array_kwh": list(point.array_kwh) if point is not None else [],
            "array_kw": list(point.array_kw) if point is not None else [],
            "array_gti_wm2": list(point.array_gti_wm2) if point is not None else [],
            "group_kw": dict(point.group_kw) if point is not None else {},
            "clipped_groups": list(point.clipped_groups) if point is not None else [],
            "selection": "first_future_slot",
        }


class DOEMSSolarForecastDailySensor(DOEMSSolarBaseSensor):
    """Expose total and per-array energy for today or tomorrow."""

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_icon = "mdi:solar-power"

    def __init__(
        self,
        entry: ConfigEntry,
        manager: SolarForecastManager,
        day: str,
    ) -> None:
        super().__init__(entry, manager)
        if day not in {"today", "tomorrow"}:
            raise ValueError("unsupported_solar_daily_sensor")
        self.day = day
        object_id = f"doems_solar_forecast_{day}_total"
        self._attr_name = f"DOEMS Solar Forecast {day.title()} Total"
        self._attr_unique_id = object_id
        self._attr_suggested_object_id = object_id

    def _target_date(self):
        local_today = dt_util.as_local(dt_util.utcnow()).date()
        return local_today if self.day == "today" else local_today + timedelta(days=1)

    @property
    def native_value(self) -> float | None:
        return self.manager.energy_for_local_date(self._target_date())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        target = self._target_date()
        contract = self.manager.contract
        return {
            "status": self.manager.source_status,
            "date": target.isoformat(),
            "array_ids": contract.get("array_ids", []),
            "array_names": contract.get("array_names", []),
            "array_energy_kwh": self.manager.array_energy_for_local_date(target),
            "topology_signature": contract.get("topology_signature"),
        }


class DOEMSSolarForecastModelSensor(DOEMSSolarBaseSensor):
    """Expose the provider-neutral P3.1 model contract."""

    _attr_name = "DOEMS Solar Forecast Model"
    _attr_unique_id = "doems_solar_forecast_model"
    _attr_suggested_object_id = "doems_solar_forecast_model"
    _attr_icon = "mdi:information-outline"

    @property
    def native_value(self) -> str:
        return SOLAR_FORECAST_MODEL

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        contract = dict(self.manager.contract)
        contract.update(
            {
                "provider": "Open-Meteo",
                "attribution": "Weather data by Open-Meteo.com",
                "endpoint": OPEN_METEO_SOLAR_ENDPOINT,
                "calculation": "gti/1000 x array_dc_kwp x performance_factor; cap inverter-group sum and scale member arrays proportionally",
                "mode": "forecast_only_no_physical_execution",
            }
        )
        return contract
