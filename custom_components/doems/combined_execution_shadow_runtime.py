"""R9 Combined execution runtime; physical authority deliberately disabled."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Callable

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .combined_anker_bridge import CombinedAnkerBridge
from .execution_anker_adapter import AnkerExecutionAdapter


class DOEMSCombinedExecutionShadowRuntime:
    def __init__(self, hass: Any, planner: Any, battery: Any = None) -> None:
        self.hass = hass
        self.planner = planner
        self.adapter = AnkerExecutionAdapter(hass, {}, authority=False)
        self.bridge = CombinedAnkerBridge(planner, self.adapter, battery=battery, authority=False, exclusive=False)
        self.last_result: dict[str, Any] = {"status": "blocked", "reason": "startup"}
        self._unsubs: list[Callable[[], None]] = []
        self._shutdown = False
        self._task: asyncio.Task | None = None
        self._dirty = False
        self._listeners: list[Callable[[], None]] = []

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
        return remove

    async def async_setup(self) -> None:
        self._unsubs.append(self.planner.async_add_listener(self.refresh))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))
        self.refresh()

    def _tick(self, _now: Any) -> None:
        self.refresh()

    def refresh(self) -> None:
        if self._shutdown:
            return
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self._drain())

    async def _drain(self) -> None:
        while self._dirty and not self._shutdown:
            self._dirty = False
            await self._evaluate()

    async def _evaluate(self) -> None:
        try:
            self.last_result = await self.bridge.async_reconcile(dt_util.utcnow())
        except Exception as exc:
            self.last_result = {"status": "blocked", "reason": "bridge_error", "error_type": type(exc).__name__}
        for listener in tuple(self._listeners):
            listener()

    async def async_shutdown(self) -> None:
        self._shutdown = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._task is not None:
            await self._task
        await self.bridge.async_shutdown()
        self._listeners.clear()
