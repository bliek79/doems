"""Registered Home Assistant SensorEntity contract for DOEMS Prices P4."""

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
    NAME,
    VERSION,
)
from .prices import DOEMSPricesManager


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the shared DOEMS device identity."""
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
    """Build the public registered Prices P4 sensor contract."""
    entities: list[SensorEntity] = [
        DOEMSPricesStatusSensor(entry, manager),
        DOEMSPricesMarketCurrentSensor(entry, manager),
        DOEMSPricesImportCurrentSensor(entry, manager),
        DOEMSPricesExportCurrentSensor(entry, manager),
        DOEMSPricesTimelineSensor(entry, manager),
        DOEMSPricesTariffProfileSensor(entry, manager),
    ]
    if manager.gas_enabled:
        entities.extend(
            [
                DOEMSPricesGasMarketSensor(entry, manager),
                DOEMSPricesGasAllInSensor(entry, manager),
                DOEMSPricesGasVsElectricitySensor(entry, manager),
            ]
        )
    return entities


class DOEMSPricesBaseSensor(SensorEntity):
    """Base class for push-updated registered Prices entities."""

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
    """Expose Prices source/runtime health."""

    _attr_name = "DOEMS Prices Status"
    _attr_unique_id = "doems_prices_status"
    _attr_suggested_object_id = "doems_prices_status"
    _attr_icon = "mdi:currency-eur"

    @property
    def native_value(self) -> str:
        return self.manager.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.manager.attributes)


class DOEMSPricesCurrentBaseSensor(DOEMSPricesBaseSensor):
    """Base class for current market/import/export prices."""

    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = "mdi:cash-clock"
    price_basis = ""

    @property
    def _point(self):
        return self.manager.current_point

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        point = self._point
        attrs = dict(self.manager.attributes)
        if point is not None:
            attrs.update(point.as_dict())
        attrs["price_basis"] = self.price_basis
        return attrs


class DOEMSPricesMarketCurrentSensor(DOEMSPricesCurrentBaseSensor):
    _attr_name = "DOEMS Prices Market Current"
    _attr_unique_id = "doems_prices_market_current"
    _attr_suggested_object_id = "doems_prices_market_current"
    price_basis = "market_incl_vat"

    @property
    def native_value(self) -> float | None:
        point = self._point
        return point.market_incl_vat if point is not None else None


class DOEMSPricesImportCurrentSensor(DOEMSPricesCurrentBaseSensor):
    _attr_name = "DOEMS Prices Import Current"
    _attr_unique_id = "doems_prices_import_current"
    _attr_suggested_object_id = "doems_prices_import_current"
    _attr_icon = "mdi:transmission-tower-import"
    price_basis = "marginal_import_all_in"

    @property
    def native_value(self) -> float | None:
        point = self._point
        return point.import_all_in if point is not None else None


class DOEMSPricesExportCurrentSensor(DOEMSPricesCurrentBaseSensor):
    _attr_name = "DOEMS Prices Export Current"
    _attr_unique_id = "doems_prices_export_current"
    _attr_suggested_object_id = "doems_prices_export_current"
    _attr_icon = "mdi:transmission-tower-export"
    price_basis = "marginal_export_all_in"

    @property
    def native_value(self) -> float | None:
        point = self._point
        return point.export_all_in if point is not None else None


class DOEMSPricesTimelineSensor(DOEMSPricesBaseSensor):
    """Expose the canonical 72-hour/288-slot Prices timeline."""

    _attr_name = "DOEMS Prices Timeline"
    _attr_unique_id = "doems_prices_timeline"
    _attr_suggested_object_id = "doems_prices_timeline"
    _attr_native_unit_of_measurement = "slots"
    _attr_icon = "mdi:chart-line"
    _unrecorded_attributes = frozenset({"points"})

    @property
    def native_value(self) -> int:
        return len(self.manager.points)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self.manager.attributes,
            "point_format": "{time, market_ex_vat, market_incl_vat, import_all_in, export_all_in, kind, source_resolution_minutes, ...}",
            "recorder_recommendation": "exclude this timeline sensor from Recorder",
            "points": list(self.manager.timeline_slots),
        }


class DOEMSPricesTariffProfileSensor(DOEMSPricesBaseSensor):
    """Expose the active immutable tariff profile snapshot."""

    _attr_name = "DOEMS Prices Tariff Profile"
    _attr_unique_id = "doems_prices_tariff_profile"
    _attr_suggested_object_id = "doems_prices_tariff_profile"
    _attr_icon = "mdi:receipt-text-check-outline"

    @property
    def native_value(self) -> str:
        profile_id = self.manager.tariff_snapshot.get("profile_id")
        return str(profile_id or "unconfigured")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.manager.tariff_snapshot)


class DOEMSPricesGasMarketSensor(DOEMSPricesBaseSensor):
    """Expose the configured external gas market source."""

    _attr_name = "DOEMS Prices Gas Market"
    _attr_unique_id = "doems_prices_gas_market"
    _attr_suggested_object_id = "doems_prices_gas_market"
    _attr_native_unit_of_measurement = "EUR/m3"
    _attr_icon = "mdi:fire"

    @property
    def native_value(self) -> float | None:
        return self.manager.gas_market_price

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self.manager.gas_source_attributes,
            "physical_execution_authority": False,
        }


class DOEMSPricesGasAllInSensor(DOEMSPricesBaseSensor):
    """Expose all-in gas price from market plus configured variable components."""

    _attr_name = "DOEMS Prices Gas All In"
    _attr_unique_id = "doems_prices_gas_all_in"
    _attr_suggested_object_id = "doems_prices_gas_all_in"
    _attr_native_unit_of_measurement = "EUR/m3"
    _attr_icon = "mdi:fire-circle"

    @property
    def native_value(self) -> float | None:
        return self.manager.gas_all_in_price

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tariff = self.manager.tariff_snapshot
        return {
            **self.manager.gas_source_attributes,
            "market_price": self.manager.gas_market_price,
            "variable_addon_incl_vat": round(self.manager.gas_variable_addon, 6),
            "gas_supplier_incl_vat": tariff.get("gas_supplier_incl_vat"),
            "gas_tax_incl_vat": tariff.get("gas_tax_incl_vat"),
            "gas_fixed_supply_per_day": tariff.get("gas_fixed_supply_per_day"),
            "gas_grid_per_day": tariff.get("gas_grid_per_day"),
            "tariff_profile_id": tariff.get("profile_id"),
            "physical_execution_authority": False,
        }



class DOEMSPricesGasVsElectricitySensor(DOEMSPricesBaseSensor):
    """Expose gas all-in normalized to EUR/kWh with electricity comparison."""

    _attr_name = "DOEMS Prices Gas vs Electricity"
    _attr_unique_id = "doems_prices_gas_vs_electricity"
    _attr_suggested_object_id = "doems_prices_gas_vs_electricity"
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = "mdi:lightning-bolt-circle"

    @property
    def native_value(self) -> float | None:
        return self.manager.gas_equivalent_price_eur_kwh

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self.manager.gas_source_attributes,
            **self.manager.gas_vs_electricity_attributes,
            "physical_execution_authority": False,
        }
