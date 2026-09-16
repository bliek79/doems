"""Runtime manager for the one-time Alpha41 Solar reference freeze."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import SOLAR_REFERENCE_FREEZE_STORAGE_KEY, SOLAR_REFERENCE_FREEZE_STORAGE_VERSION
from .solar_reference_freeze import REFERENCE_ENTITY_IDS, build_snapshot, validate_reference


class SolarReferenceFreezeManager:
    """Validate Alpha41 public Solar state and persist exactly one immutable snapshot."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store: Store[dict[str, Any]] = Store(
            hass,
            SOLAR_REFERENCE_FREEZE_STORAGE_VERSION,
            SOLAR_REFERENCE_FREEZE_STORAGE_KEY,
        )
        self.snapshot: dict[str, Any] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._remove_source_listener: Callable[[], None] | None = None

    async def async_setup(self) -> None:
        stored = await self.store.async_load() or {}
        snapshot = stored.get("snapshot")
        if isinstance(snapshot, dict):
            self.snapshot = snapshot
            return
        self._remove_source_listener = async_track_state_change_event(
            self.hass, list(REFERENCE_ENTITY_IDS), self._reference_changed
        )

    async def async_shutdown(self) -> None:
        self._stop_source_listener()
        if self.snapshot is not None:
            await self.store.async_save({"snapshot": self.snapshot})

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

    @callback
    def _reference_changed(self, _event: Event) -> None:
        self._notify()

    def _stop_source_listener(self) -> None:
        if self._remove_source_listener is not None:
            self._remove_source_listener()
            self._remove_source_listener = None

    def _state_payloads(self) -> dict[str, dict[str, Any]]:
        payloads: dict[str, dict[str, Any]] = {}
        for entity_id in REFERENCE_ENTITY_IDS:
            state = self.hass.states.get(entity_id)
            if state is not None:
                payloads[entity_id] = {"state": state.state, "attributes": dict(state.attributes)}
        return payloads

    @property
    def blockers(self) -> list[str]:
        if self.snapshot is not None:
            return []
        return validate_reference(self._state_payloads())

    @property
    def status(self) -> str:
        if self.snapshot is not None:
            return "captured"
        return "ready" if not self.blockers else "blocked"

    @property
    def capture_available(self) -> bool:
        return self.snapshot is None and not self.blockers

    async def async_capture(self) -> dict[str, Any]:
        if self.snapshot is not None:
            raise HomeAssistantError(
                f"Solar reference already captured as {self.snapshot.get('snapshot_id', 'unknown')}"
            )
        states = self._state_payloads()
        blockers = validate_reference(states)
        if blockers:
            raise HomeAssistantError("Solar freeze blocked: " + "; ".join(blockers))
        captured_at_utc = dt_util.utcnow()
        snapshot = build_snapshot(
            states,
            captured_at_utc=captured_at_utc,
            captured_at_local=dt_util.as_local(captured_at_utc),
        )
        await self.store.async_save({"snapshot": snapshot})
        self.snapshot = snapshot
        self._stop_source_listener()
        self._notify()
        return snapshot
