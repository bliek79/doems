"""Public Home Assistant sensors for DOEMS Prices P4.1."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_INSTANCE_NAME,
    DEFAULT_INSTANCE_NAME,
    DEVICE_IDENTIFIER,
    DOMAIN,
    FORECAST_HORIZON_HOURS,
    FORECAST_SLOTS,
    NAME,
    QUARTER_MINUTES,
    VERSION,
)
from .prices import DOEMSPricesManager, FORECAST_URL, PRICES_URL


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
        name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
        manufacturer=NAME,
        model="Energy Management System",
        sw_version=VERSION,
    )


def build_prices_sensors(
    entry: ConfigEntry,
    manager: DOEMSPricesManager,
) -> list[SensorEntity]:
    """Build the public provider-neutral Prices P4.1 sensor contract."""
    sensors: list[SensorEntity] = [
        DOEMSPricesStatusSensor(entry, manager),
        DOEMSPricesCurrentSensor(entry, manager, "market"),
        DOEMSPricesCurrentSensor(entry, manager, "import"),
        DOEMSPricesCurrentSensor(entry, manager, "export"),
        DOEMSPricesTimelineSensor(entry, manager),
        DOEMSPricesTariffProfileSensor(entry, manager),
    ]
    if manager.gas_enabled:
        sensors.extend(
            [
                DOEMSPricesGasSensor(entry, manager, "market"),
                DOEMSPricesGasSensor(entry, manager, "all_in"),
            ]
        )
    return sensors


class DOEMSPricesBaseSensor(SensorEntity):
    """Base class for push-updated Prices entities."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, entry: ConfigEntry, manager: DOEMSPricesManager) -> None:
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


class DOEMSPricesStatusSensor(DOEMSPricesBaseSensor):
    """Expose source health and normalized Prices diagnostics."""

    _attr_name = "DOEMS Prices Status"
    _attr_unique_id = "doems_prices_status"
    _attr_suggested_object_id = "doems_prices_status"
    _attr_icon = "mdi:currency-eur"

    @property
    def native_value(self) -> str:
        return self.manager.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self.manager.common_attributes,
            "prices_endpoint": PRICES_URL,
            "forecast_endpoint": FORECAST_URL,
            "timeline_entity": "sensor.doems_prices_timeline",
            "import_entity": "sensor.doems_prices_import_current",
            "export_entity": "sensor.doems_prices_export_current",
        }


class DOEMSPricesCurrentSensor(DOEMSPricesBaseSensor):
    """Expose market/import/export value for the known actual current quarter."""

    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = "mdi:cash-clock"

    def __init__(
        self,
        entry: ConfigEntry,
        manager: DOEMSPricesManager,
        kind: str,
    ) -> None:
        super().__init__(entry, manager)
        if kind not in {"market", "import", "export"}:
            raise ValueError("unsupported_price_current_kind")
        self.kind = kind
        self._attr_name = f"DOEMS Prices {kind.title()} Current"
        self._attr_unique_id = f"doems_prices_{kind}_current"
        self._attr_suggested_object_id = f"doems_prices_{kind}_current"

    @property
    def native_value(self) -> float | None:
        point = self.manager.current_point
        if point is None:
            return None
        if self.kind == "market":
            return point.market_incl_vat
        if self.kind == "import":
            return point.import_all_in
        return point.export_all_in

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        point = self.manager.current_point
        point_attrs = point.as_dict() if point else {}
        basis = {
            "market": "market_incl_vat",
            "import": "marginal_import_all_in",
            "export": "marginal_export_all_in",
        }[self.kind]
        return {
            **self.manager.common_attributes,
            **point_attrs,
            "price_basis": basis,
            "current_semantics": "actual_current_quarter_known_only",
            "fixed_daily_costs_included": False,
        }


class DOEMSPricesTimelineSensor(DOEMSPricesBaseSensor):
    """Expose the canonical positional 288-slot Prices timeline."""

    _attr_name = "DOEMS Prices Timeline"
    _attr_unique_id = "doems_prices_timeline"
    _attr_suggested_object_id = "doems_prices_timeline"
    _attr_icon = "mdi:chart-line"
    _unrecorded_attributes = frozenset({"points"})

    @property
    def native_value(self) -> int:
        return len(self.manager.points)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self.manager.common_attributes,
            "slot_count": FORECAST_SLOTS,
            "point_count": FORECAST_SLOTS if self.manager.timeline_start else 0,
            "resolution_minutes": QUARTER_MINUTES,
            "horizon_hours": FORECAST_HORIZON_HOURS,
            "point_format": "dict:v1",
            "point_fields": [
                "time",
                "market_ex_vat",
                "market_incl_vat",
                "import_all_in",
                "export_all_in",
                "kind",
                "source_resolution_minutes",
                "lower_ex_vat",
                "upper_ex_vat",
                "forecast_generated_at",
                "uncertainty_pct",
                "regime",
                "valid",
            ],
            "import_series_field": "import_all_in",
            "export_series_field": "export_all_in",
            "known_vs_forecast_field": "kind",
            "missing_semantics": "explicit_null_record_keeps_slot_position",
            "recorder_points": "excluded",
            "points": self.manager.timeline_points(),
        }


class DOEMSPricesTariffProfileSensor(DOEMSPricesBaseSensor):
    """Expose the complete active tariff profile to third-party consumers."""

    _attr_name = "DOEMS Prices Tariff Profile"
    _attr_unique_id = "doems_prices_tariff_profile"
    _attr_suggested_object_id = "doems_prices_tariff_profile"
    _attr_icon = "mdi:file-document-edit-outline"

    @property
    def native_value(self) -> str:
        return str(self.manager.tariff_snapshot["profile_id"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.manager.tariff_snapshot


class DOEMSPricesGasSensor(DOEMSPricesBaseSensor):
    """Optional current gas market/all-in companion sensor; not a forecast."""

    _attr_native_unit_of_measurement = "EUR/m3"
    _attr_icon = "mdi:fire"

    def __init__(
        self,
        entry: ConfigEntry,
        manager: DOEMSPricesManager,
        kind: str,
    ) -> None:
        super().__init__(entry, manager)
        if kind not in {"market", "all_in"}:
            raise ValueError("unsupported_gas_price_kind")
        self.kind = kind
        suffix = "Market" if kind == "market" else "All In"
        self._attr_name = f"DOEMS Prices Gas {suffix}"
        self._attr_unique_id = f"doems_prices_gas_{kind}"
        self._attr_suggested_object_id = f"doems_prices_gas_{kind}"

    @property
    def native_value(self) -> float | None:
        return (
            self.manager.gas_market_price
            if self.kind == "market"
            else self.manager.gas_all_in_price
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tariff = self.manager.tariff_snapshot
        return {
            "source_entity": self.manager.gas_market_entity,
            "tariff_profile_id": tariff["profile_id"],
            "tariff_valid_from": tariff["valid_from"],
            "price_basis": (
                "external_gas_market"
                if self.kind == "market"
                else "gas_market_plus_variable_tariff"
            ),
            "market_price_incl_vat": self.manager.gas_market_price,
            "variable_addon_incl_vat": round(self.manager.gas_variable_addon, 6),
            "gas_fixed_supply_per_day": tariff["gas_fixed_supply_per_day"],
            "gas_grid_per_day": tariff["gas_grid_per_day"],
            "fixed_daily_costs_included": False,
            "physical_execution_authority": False,
        }
