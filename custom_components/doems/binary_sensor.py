"""DOEMS diagnostic binary sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_INSTANCE_NAME,
    DEFAULT_INSTANCE_NAME,
    DEVICE_IDENTIFIER,
    DOMAIN,
    NAME,
    SOLAR_FOUNDATION_STORAGE_KEY,
    VERSION,
)
from .presence import DOEMSPresenceStore
from .solar_foundation import SolarFoundationManager


def _foundation_manager(hass: HomeAssistant, entry: ConfigEntry) -> SolarFoundationManager:
    return hass.data[DOMAIN][entry.entry_id]["solar_foundation"]


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
    entities: list[BinarySensorEntity] = [
        DOEMSSolarFoundationReadySensor(entry, _foundation_manager(hass, entry)),
    ]
    presence = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("presence")
    if isinstance(presence, DOEMSPresenceStore):
        entities.extend(
            [
                DOEMSAwayActiveSensor(entry, presence),
                DOEMSAwayScheduleValidSensor(entry, presence),
            ]
        )
    async_add_entities(entities)


class DOEMSSolarFoundationReadySensor(BinarySensorEntity):
    """Expose the generic Solar P3.0 install/topology contract."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS Solar Foundation Ready"
    _attr_unique_id = "doems_solar_foundation_ready"
    _attr_suggested_object_id = "doems_solar_foundation_ready"
    _attr_icon = "mdi:solar-panel-large"
    _unrecorded_attributes = frozenset({"inverter_groups", "arrays"})

    def __init__(self, entry: ConfigEntry, manager: SolarFoundationManager) -> None:
        self.manager = manager
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        return self.manager.status == "ready"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snapshot = self.manager.snapshot
        return {
            "status": snapshot.get("status"),
            "enabled": snapshot.get("enabled"),
            "schema_version": snapshot.get("schema_version"),
            "provider": snapshot.get("provider"),
            "location_source": snapshot.get("location_source"),
            "latitude": snapshot.get("latitude"),
            "longitude": snapshot.get("longitude"),
            "azimuth_contract": snapshot.get("azimuth_contract"),
            "inverter_group_count": snapshot.get("inverter_group_count", 0),
            "array_count": snapshot.get("array_count", 0),
            "total_dc_kwp": snapshot.get("total_dc_kwp", 0.0),
            "known_ac_limit_kw": snapshot.get("known_ac_limit_kw", 0.0),
            "ac_limits_complete": snapshot.get("ac_limits_complete", False),
            "total_actual_configured": snapshot.get("total_actual_configured", False),
            "total_actual_power_entity": snapshot.get("total_actual_power_entity"),
            "per_array_actual_count": snapshot.get("per_array_actual_count", 0),
            "blockers": snapshot.get("blockers", []),
            "topology_signature": snapshot.get("topology_signature"),
            "native_time_contract": snapshot.get("native_time_contract"),
            "inverter_groups": snapshot.get("inverter_groups", []),
            "arrays": snapshot.get("arrays", []),
            "storage_key": SOLAR_FOUNDATION_STORAGE_KEY,
            "forecast_runtime_active": self.manager.forecast_runtime_active,
            "physical_execution_authority": False,
        }



class _DOEMSPresenceBinarySensor(BinarySensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, entry: ConfigEntry, presence: DOEMSPresenceStore) -> None:
        self.presence = presence
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

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


class DOEMSAwayActiveSensor(_DOEMSPresenceBinarySensor):
    _attr_name = "DOEMS Away Active"
    _attr_unique_id = "doems_away_active"
    _attr_suggested_object_id = "doems_away_active"
    _attr_icon = "mdi:home-export-outline"

    @property
    def is_on(self) -> bool:
        return self.presence.effective_profile == "away"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "effective_profile": self.presence.effective_profile,
            "profile_source": self.presence.profile_source,
            "schedule_active": self.presence.schedule_active,
            "manual_override_active": self.presence.manual_override_active,
        }


class DOEMSAwayScheduleValidSensor(_DOEMSPresenceBinarySensor):
    _attr_name = "DOEMS Away Schedule Valid"
    _attr_unique_id = "doems_away_schedule_valid"
    _attr_suggested_object_id = "doems_away_schedule_valid"
    _attr_icon = "mdi:calendar-check-outline"

    @property
    def is_on(self) -> bool:
        return self.presence.schedule_valid

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "schedule_enabled": self.presence.schedule_enabled,
            "away_start": self.presence.away_start.isoformat() if self.presence.away_start else None,
            "away_end": self.presence.away_end.isoformat() if self.presence.away_end else None,
            "blockers": list(self.presence.blockers),
        }
