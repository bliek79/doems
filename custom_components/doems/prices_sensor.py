"""Public Prices P4.1 sensors for DOEMS."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DEVICE_IDENTIFIER, DOMAIN, NAME, VERSION
from .prices import DOEMSPricesManager

PRICE_UNIT = "EUR/kWh"
GAS_PRICE_UNIT = "EUR/m³"


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
        name=entry.options.get("instance_name", NAME),
        manufacturer=NAME,
        model="Energy Management System",
        sw_version=VERSION,
    )


def build_prices_sensors(
    entry: ConfigEntry,
    manager: DOEMSPricesManager,
) -> list[SensorEntity]:
    """Return the stable public Prices entity set."""
    entities: list[SensorEntity] = [
        DOEMSPricesStatusSensor(entry, manager),
        DOEMSPricesCurrentSensor(entry, manager, "market"),
        DOEMSPricesCurrentSensor(entry, manager, "import"),
        DOEMSPricesCurrentSensor(entry, manager, "export"),
        DOEMSPricesTimelineSensor(entry, manager),
        DOEMSPricesTariffProfileSensor(entry, manager),
    ]
    if manager.gas_enabled:
        entities.extend(
            [
                DOEMSGasPriceSensor(entry, manager, "market"),
                DOEMSGasPriceSensor(entry, manager, "all_in"),
            ]
        )
    return entities


class DOEMSPricesBaseSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, entry: ConfigEntry, manager: DOEMSPricesManager) -> None:
        self.entry = entry
        self.manager = manager
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.manager.async_add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class DOEMSPricesStatusSensor(DOEMSPricesBaseSensor):
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


class DOEMSPricesCurrentSensor(DOEMSPricesBaseSensor):
    _attr_native_unit_of_measurement = PRICE_UNIT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        entry: ConfigEntry,
        manager: DOEMSPricesManager,
        kind: str,
    ) -> None:
        super().__init__(entry, manager)
        self.kind = kind
        labels = {
            "market": ("DOEMS Prices Market Current", "doems_prices_market_current", "mdi:chart-line"),
            "import": ("DOEMS Prices Import Current", "doems_prices_import_current", "mdi:transmission-tower-import"),
            "export": ("DOEMS Prices Export Current", "doems_prices_export_current", "mdi:transmission-tower-export"),
        }
        name, object_id, icon = labels[kind]
        self._attr_name = name
        self._attr_unique_id = object_id
        self._attr_suggested_object_id = object_id
        self._attr_icon = icon

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
            **self.manager.attributes,
            **point_attrs,
            "price_basis": basis,
        }


class DOEMSPricesTimelineSensor(DOEMSPricesBaseSensor):
    _attr_name = "DOEMS Prices Timeline"
    _attr_unique_id = "doems_prices_timeline"
    _attr_suggested_object_id = "doems_prices_timeline"
    _attr_icon = "mdi:chart-timeline-variant"
    _unrecorded_attributes = frozenset({"points"})

    @property
    def native_value(self) -> int:
        return len(self.manager.points)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self.manager.attributes,
            "point_count": len(self.manager.points),
            "point_format": "dict(time, market_ex_vat, market_incl_vat, import_all_in, export_all_in, kind, source_resolution_minutes, forecast metadata)",
            "recorder_points": "excluded",
            "apex_primary_lines": ["import_all_in", "export_all_in"],
            "points": [point.as_dict() for point in self.manager.points],
        }


class DOEMSPricesTariffProfileSensor(DOEMSPricesBaseSensor):
    _attr_name = "DOEMS Prices Tariff Profile"
    _attr_unique_id = "doems_prices_tariff_profile"
    _attr_suggested_object_id = "doems_prices_tariff_profile"
    _attr_icon = "mdi:receipt-text-outline"

    @property
    def native_value(self) -> str:
        return str(self.manager.tariff_snapshot.get("profile_id") or "unconfigured")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.manager.tariff_snapshot)


class DOEMSGasPriceSensor(DOEMSPricesBaseSensor):
    _attr_native_unit_of_measurement = GAS_PRICE_UNIT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        entry: ConfigEntry,
        manager: DOEMSPricesManager,
        kind: str,
    ) -> None:
        super().__init__(entry, manager)
        self.kind = kind
        if kind == "market":
            self._attr_name = "DOEMS Prices Gas Market"
            self._attr_unique_id = "doems_prices_gas_market"
            self._attr_suggested_object_id = "doems_prices_gas_market"
            self._attr_icon = "mdi:gas-cylinder"
        else:
            self._attr_name = "DOEMS Prices Gas All-in"
            self._attr_unique_id = "doems_prices_gas_all_in"
            self._attr_suggested_object_id = "doems_prices_gas_all_in"
            self._attr_icon = "mdi:cash-multiple"

    @property
    def native_value(self) -> float | None:
        if self.kind == "market":
            return self.manager.gas_market_price
        return self.manager.gas_all_in_price

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self.manager.tariff_snapshot,
            "source_entity": self.manager.gas_market_entity,
            "price_basis": "external_market" if self.kind == "market" else "gas_all_in_variable",
            "physical_execution_authority": False,
        }
