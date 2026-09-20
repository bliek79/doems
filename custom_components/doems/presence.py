"""Persistent DOEMS presence/Away runtime state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AWAY_END,
    CONF_AWAY_SCHEDULE_ENABLED,
    CONF_AWAY_START,
    CONF_ENERGY_START_PROFILE,
    PRESENCE_STORAGE_KEY,
    PRESENCE_STORAGE_VERSION,
    PROFILE_AWAY,
    PROFILE_LEARNING_OPTIONS,
    PROFILE_NORMAL,
    PROFILE_UNCLASSIFIED,
)
from .energy_coordinator import DOEMSEnergyCoordinator


class DOEMSPresenceStore:
    """Single persistent truth for DOEMS normal/Away profile state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: DOEMSEnergyCoordinator | None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.store: Store[dict[str, Any]] = Store(
            hass, PRESENCE_STORAGE_VERSION, PRESENCE_STORAGE_KEY
        )
        self.manual_profile = PROFILE_NORMAL
        self.effective_profile = PROFILE_UNCLASSIFIED
        self.profile_source = "initializing"
        self.previous_profile: str | None = None
        self.pre_schedule_profile: str | None = None
        self.profile_changed_at: str | None = None
        self.change_reason = "initializing"
        self.restart_restored = False

        self.schedule_enabled = False
        self.away_start: datetime | None = None
        self.away_end: datetime | None = None
        self.schedule_valid = False
        self.schedule_active = False
        self.schedule_applied = False
        self.manual_override_active = False
        self.schedule_window_id: str | None = None
        self.override_window_id: str | None = None
        self.blockers: list[str] = []

        self._listeners: list[Callable[[], None]] = []
        self._boundary_unsub: Callable[[], None] | None = None

    async def async_setup(self) -> None:
        """Restore persistent state and evaluate current schedule state."""
        stored = await self.store.async_load()
        if isinstance(stored, dict):
            self._restore(stored)
            self.restart_restored = True
        else:
            self._initialize_from_existing_state()
            self.restart_restored = False

        await self.async_refresh(reason="restart_restore", save=False)
        await self._async_save()
        self._schedule_next_boundary()

    def _initialize_from_existing_state(self) -> None:
        """Seed the new store from the existing profile and legacy Away options."""
        candidate = (
            self.coordinator.profile
            if self.coordinator is not None
            else self.entry.options.get(CONF_ENERGY_START_PROFILE, PROFILE_NORMAL)
        )
        self.manual_profile = (
            candidate if candidate in PROFILE_LEARNING_OPTIONS else PROFILE_UNCLASSIFIED
        )
        self.previous_profile = (
            self.coordinator.previous_profile if self.coordinator is not None else None
        )
        self.profile_changed_at = (
            self.coordinator.profile_changed_at if self.coordinator is not None else None
        )
        self.schedule_enabled = bool(
            self.entry.options.get(CONF_AWAY_SCHEDULE_ENABLED, False)
        )
        self.away_start = self._parse_datetime(self.entry.options.get(CONF_AWAY_START))
        self.away_end = self._parse_datetime(self.entry.options.get(CONF_AWAY_END))
        self.change_reason = "presence_store_migrated"
        self.profile_source = "migration"

    def _restore(self, stored: dict[str, Any]) -> None:
        manual = stored.get("manual_profile")
        self.manual_profile = (
            manual if manual in PROFILE_LEARNING_OPTIONS else PROFILE_UNCLASSIFIED
        )
        effective = stored.get("effective_profile")
        self.effective_profile = (
            effective
            if effective in (PROFILE_NORMAL, PROFILE_AWAY, PROFILE_UNCLASSIFIED)
            else PROFILE_UNCLASSIFIED
        )
        self.profile_source = str(stored.get("profile_source") or "restored")
        self.previous_profile = stored.get("previous_profile")
        self.pre_schedule_profile = stored.get("pre_schedule_profile")
        self.profile_changed_at = stored.get("profile_changed_at")
        self.change_reason = str(stored.get("change_reason") or "restart_restore")

        self.schedule_enabled = bool(stored.get("schedule_enabled", False))
        self.away_start = self._parse_datetime(stored.get("away_start"))
        self.away_end = self._parse_datetime(stored.get("away_end"))
        self.schedule_applied = bool(stored.get("schedule_applied", False))
        self.manual_override_active = bool(
            stored.get("manual_override_active", False)
        )
        self.schedule_window_id = stored.get("schedule_window_id")
        self.override_window_id = stored.get("override_window_id")

    def _parse_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str) and value.strip():
            parsed = dt_util.parse_datetime(value.strip())
        else:
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            zone = dt_util.get_time_zone(self.hass.config.time_zone)
            parsed = parsed.replace(tzinfo=zone or dt_util.DEFAULT_TIME_ZONE)
        return parsed

    def _window_id(self) -> str | None:
        if self.away_start is None or self.away_end is None:
            return None
        return f"{self.away_start.isoformat()}|{self.away_end.isoformat()}"

    def _evaluate_schedule(self, now: datetime) -> tuple[bool, bool, list[str]]:
        blockers: list[str] = []
        valid = (
            self.away_start is not None
            and self.away_end is not None
            and self.away_end > self.away_start
        )
        if self.schedule_enabled and self.away_start is None:
            blockers.append("away_start_missing")
        if self.schedule_enabled and self.away_end is None:
            blockers.append("away_end_missing")
        if (
            self.schedule_enabled
            and self.away_start is not None
            and self.away_end is not None
            and self.away_end <= self.away_start
        ):
            blockers.append("away_window_invalid")

        active = False
        if self.schedule_enabled and valid:
            now_local = dt_util.as_local(dt_util.as_utc(now))
            active = self.away_start <= now_local < self.away_end
        return valid, active, blockers

    async def async_refresh(
        self,
        *,
        reason: str,
        now: datetime | None = None,
        save: bool = True,
    ) -> None:
        """Re-evaluate effective profile from manual profile and Away schedule."""
        reference = now or dt_util.now()
        valid, active, blockers = self._evaluate_schedule(reference)
        window_id = self._window_id()

        if active and window_id != self.schedule_window_id:
            self.schedule_window_id = window_id
            self.schedule_applied = False
            self.manual_override_active = False
            self.override_window_id = None
            self.pre_schedule_profile = None

        if active and not self.schedule_applied:
            self.pre_schedule_profile = self.manual_profile
            self.schedule_applied = True

        if self.schedule_enabled and not valid:
            target = PROFILE_UNCLASSIFIED
            source = "invalid_away_schedule"
        elif active:
            if (
                self.manual_override_active
                and self.override_window_id == window_id
            ):
                target = self.manual_profile
                source = "manual_override"
            else:
                target = PROFILE_AWAY
                source = "away_schedule"
        else:
            target = (
                self.manual_profile
                if self.manual_profile in PROFILE_LEARNING_OPTIONS
                else PROFILE_UNCLASSIFIED
            )
            source = "manual" if target != PROFILE_UNCLASSIFIED else "unclassified"

            if self.schedule_active:
                self.schedule_applied = False
                self.manual_override_active = False
                self.override_window_id = None
                self.schedule_window_id = None
                self.pre_schedule_profile = None

        if self.manual_profile not in PROFILE_LEARNING_OPTIONS:
            if "manual_profile_invalid" not in blockers:
                blockers.append("manual_profile_invalid")
            target = PROFILE_UNCLASSIFIED
            source = "invalid_manual_profile"

        old_effective = self.effective_profile
        self.schedule_valid = valid
        self.schedule_active = active
        self.blockers = blockers

        if target != old_effective:
            self.previous_profile = old_effective
            self.effective_profile = target
            self.profile_source = source
            self.profile_changed_at = dt_util.as_utc(reference).isoformat()
            self.change_reason = reason
        else:
            self.profile_source = source
            self.change_reason = reason

        await self._sync_energy_profile(reason=reason)
        if save:
            await self._async_save()
        self._schedule_next_boundary()
        self._notify()

    async def _sync_energy_profile(self, *, reason: str) -> None:
        if self.coordinator is None:
            return
        if self.coordinator.profile == self.effective_profile:
            return
        await self.coordinator.async_set_profile(
            self.effective_profile,
            source=f"presence:{reason}",
        )

    async def async_set_manual_profile(self, profile: str) -> None:
        if profile not in PROFILE_LEARNING_OPTIONS:
            raise ValueError(f"Unsupported presence profile: {profile}")

        valid, active, _ = self._evaluate_schedule(dt_util.now())
        window_id = self._window_id()
        self.manual_profile = profile
        if self.schedule_enabled and valid and active:
            self.manual_override_active = True
            self.override_window_id = window_id
        else:
            self.manual_override_active = False
            self.override_window_id = None
        await self.async_refresh(reason="manual_profile_change")

    async def async_set_schedule_enabled(self, enabled: bool) -> None:
        self.schedule_enabled = bool(enabled)
        if not self.schedule_enabled:
            self.schedule_applied = False
            self.manual_override_active = False
            self.override_window_id = None
            self.schedule_window_id = None
            self.pre_schedule_profile = None
        await self.async_refresh(reason="away_schedule_enabled_change")

    async def async_set_away_start(self, value: datetime) -> None:
        parsed = self._parse_datetime(value)
        if parsed is None:
            raise ValueError("Away start must be a valid datetime")
        self.away_start = parsed
        self._reset_schedule_application()
        await self.async_refresh(reason="away_start_change")

    async def async_set_away_end(self, value: datetime) -> None:
        parsed = self._parse_datetime(value)
        if parsed is None:
            raise ValueError("Away end must be a valid datetime")
        self.away_end = parsed
        self._reset_schedule_application()
        await self.async_refresh(reason="away_end_change")

    def _reset_schedule_application(self) -> None:
        self.schedule_applied = False
        self.manual_override_active = False
        self.override_window_id = None
        self.schedule_window_id = None
        self.pre_schedule_profile = None

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def remove_listener() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove_listener

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _schedule_next_boundary(self) -> None:
        if self._boundary_unsub is not None:
            self._boundary_unsub()
            self._boundary_unsub = None
        if not self.schedule_enabled or not self.schedule_valid:
            return

        now_utc = dt_util.utcnow()
        future = [
            dt_util.as_utc(value)
            for value in (self.away_start, self.away_end)
            if value is not None and dt_util.as_utc(value) > now_utc
        ]
        if not future:
            return
        self._boundary_unsub = async_track_point_in_utc_time(
            self.hass, self._async_boundary_reached, min(future)
        )

    async def _async_boundary_reached(self, now: datetime) -> None:
        self._boundary_unsub = None
        await self.async_refresh(reason="away_schedule_boundary", now=now)

    async def _async_save(self) -> None:
        await self.store.async_save(
            {
                "manual_profile": self.manual_profile,
                "effective_profile": self.effective_profile,
                "profile_source": self.profile_source,
                "previous_profile": self.previous_profile,
                "pre_schedule_profile": self.pre_schedule_profile,
                "profile_changed_at": self.profile_changed_at,
                "change_reason": self.change_reason,
                "schedule_enabled": self.schedule_enabled,
                "away_start": self.away_start.isoformat() if self.away_start else None,
                "away_end": self.away_end.isoformat() if self.away_end else None,
                "schedule_valid": self.schedule_valid,
                "schedule_active": self.schedule_active,
                "schedule_applied": self.schedule_applied,
                "manual_override_active": self.manual_override_active,
                "schedule_window_id": self.schedule_window_id,
                "override_window_id": self.override_window_id,
                "restart_restored": self.restart_restored,
                "blockers": self.blockers,
            }
        )

    async def async_shutdown(self) -> None:
        if self._boundary_unsub is not None:
            self._boundary_unsub()
            self._boundary_unsub = None
        await self._async_save()

    def context(self) -> dict[str, Any]:
        return {
            "effective_profile": self.effective_profile,
            "manual_profile": self.manual_profile,
            "profile_source": self.profile_source,
            "previous_profile": self.previous_profile,
            "pre_schedule_profile": self.pre_schedule_profile,
            "profile_changed_at": self.profile_changed_at,
            "change_reason": self.change_reason,
            "restart_restored": self.restart_restored,
            "schedule_enabled": self.schedule_enabled,
            "schedule_valid": self.schedule_valid,
            "schedule_active": self.schedule_active,
            "away_start": self.away_start.isoformat() if self.away_start else None,
            "away_end": self.away_end.isoformat() if self.away_end else None,
            "manual_override_active": self.manual_override_active,
            "blockers": list(self.blockers),
            "physical_execution_authority": False,
        }
