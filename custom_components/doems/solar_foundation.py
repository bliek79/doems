"""Persistent runtime wrapper for the DOEMS Solar P3.0 Foundation."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import SOLAR_FOUNDATION_STORAGE_KEY, SOLAR_FOUNDATION_STORAGE_VERSION
from .solar_foundation_model import build_solar_foundation_snapshot


class SolarFoundationManager:
    """Normalize and persist the generic Solar install/topology contract."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store: Store[dict[str, Any]] = Store(
            hass,
            SOLAR_FOUNDATION_STORAGE_VERSION,
            SOLAR_FOUNDATION_STORAGE_KEY,
        )
        self.snapshot: dict[str, Any] = {}

    async def async_setup(self) -> None:
        self.snapshot = build_solar_foundation_snapshot(
            dict(self.entry.options),
            ha_latitude=getattr(self.hass.config, "latitude", None),
            ha_longitude=getattr(self.hass.config, "longitude", None),
        )
        await self.store.async_save(self.snapshot)

    async def async_shutdown(self) -> None:
        if self.snapshot:
            await self.store.async_save(self.snapshot)

    @property
    def status(self) -> str:
        return str(self.snapshot.get("status", "disabled"))
