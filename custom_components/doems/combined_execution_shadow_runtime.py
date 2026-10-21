"""Read-only R9 Combined execution supervisor.

Observes planner publications and the current 15-minute slot. Never actuates.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .combined_execution_shadow import evaluate_combined_execution_shadow


class DOEMSCombinedExecutionShadowRuntime:
    def __init__(self, hass: Any, planner: Any) -> None:
        self.hass = hass
        self.planner = planner
        self.last_result: dict[str, Any] = {
            "status": "blocked",
            "reason": "startup",
            "physical_execution_enabled": False,
            "execution_performed": False,
        }
        self._unsubs: list[Callable[[], None]] = []
        self._shutdown = False

    async def async_setup(self) -> None:
        self._unsubs.append(self.planner.async_add_listener(self.refresh))
        self._unsubs.append(
            async_track_time_interval(self.hass, self._tick, timedelta(minutes=1))
        )
        self.refresh()

    def _tick(self, _now: Any) -> None:
        self.refresh()

    def refresh(self) -> None:
        if self._shutdown:
            return
        try:
            self.last_result = evaluate_combined_execution_shadow(
                self.planner.snapshot("combined"), now=dt_util.utcnow()
            )
        except (ValueError, TypeError, OverflowError):
            self.last_result = {
                "status": "blocked",
                "reason": "observer_error",
                "physical_execution_enabled": False,
                "execution_performed": False,
            }

    async def async_shutdown(self) -> None:
        self._shutdown = True
        for unsubscribe in self._unsubs:
            unsubscribe()
        self._unsubs.clear()
