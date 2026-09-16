"""DOEMS diagnostic binary sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME, DEVICE_IDENTIFIER, DOMAIN, NAME, SOLAR_REFERENCE_FREEZE_STORAGE_KEY, VERSION
from .solar_reference_freeze import REFERENCE_COMMIT, REFERENCE_RELEASE, REFERENCE_REPOSITORY
from .solar_reference_freeze_runtime import SolarReferenceFreezeManager


def _manager(hass: HomeAssistant, entry: ConfigEntry) -> SolarReferenceFreezeManager:
    return hass.data[DOMAIN][entry.entry_id]["solar_reference_freeze"]


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, DEVICE_IDENTIFIER)}, name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME), manufacturer=NAME, model="Energy Management System", sw_version=VERSION)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([DOEMSAlpha41SolarFreezeCapturedSensor(entry, _manager(hass, entry))])


class DOEMSAlpha41SolarFreezeCapturedSensor(BinarySensorEntity):
    """Expose Solar reference readiness and persistent capture state."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "DOEMS Alpha41 Solar Freeze Captured"
    _attr_unique_id = "doems_alpha41_solar_freeze_captured"
    _attr_suggested_object_id = "doems_alpha41_solar_freeze_captured"
    _attr_icon = "mdi:snowflake"
    _unrecorded_attributes = frozenset({"points"})

    def __init__(self, entry: ConfigEntry, manager: SolarReferenceFreezeManager) -> None:
        self.manager = manager
        self._remove_listener = None
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        return self.manager.snapshot is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snapshot = self.manager.snapshot
        attrs: dict[str, Any] = {
            "freeze_status": self.manager.status,
            "blockers": self.manager.blockers,
            "reference_release": REFERENCE_RELEASE,
            "reference_commit": REFERENCE_COMMIT,
            "reference_repository": REFERENCE_REPOSITORY,
            "storage_key": SOLAR_REFERENCE_FREEZE_STORAGE_KEY,
            "physical_execution_authority": False,
            "sheets_write": False,
        }
        if snapshot is None:
            return attrs

        timeline = snapshot.get("timeline", {})
        attrs.update({
            "snapshot_id": snapshot.get("snapshot_id"),
            "captured_at_utc": snapshot.get("captured_at_utc"),
            "captured_at_local": snapshot.get("captured_at_local"),
            "timeline_resolution_minutes": timeline.get("resolution_minutes"),
            "timeline_horizon_hours": timeline.get("horizon_hours"),
            "timeline_slot_count": timeline.get("point_count"),
            "timeline_point_format": timeline.get("point_format"),
            "timeline_sha256": timeline.get("raw_points_sha256"),
            "forecast_start": timeline.get("forecast_start"),
            "forecast_end": timeline.get("forecast_end"),
            "sheets_anchor_status": snapshot.get("sheets_anchor", {}).get("status"),
            "actual": snapshot.get("actual"),
            "next_quarter": snapshot.get("next_quarter"),
            "today": snapshot.get("today"),
            "tomorrow": snapshot.get("tomorrow"),
            "points": timeline.get("points"),
        })
        return attrs

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
