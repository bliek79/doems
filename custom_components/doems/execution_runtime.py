"""Read-only execution supervisor with durable transitions and fail-safe audit.

No device service is invoked. A physical adapter is intentionally not enabled:
it requires an independently authorized battery-specific command contract.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .execution_model import evaluate_execution


class DOEMSExecutionSupervisor:
    def __init__(self, hass: HomeAssistant, scheduler: Any, store: Any, battery: Any, entry_id: str) -> None:
        self.hass, self.scheduler, self.store, self.battery = hass, scheduler, store, battery
        self._storage = Store(hass, 1, f"doems.{entry_id}.execution")
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self._shutdown = False
        self._task: asyncio.Task | None = None
        self._dirty = False
        self.last_result: dict[str, Any] = {"status": "geen_actie", "execution_performed": False}
        self.history: list[dict[str, Any]] = []

    async def async_setup(self) -> None:
        stored = await self._storage.async_load()
        if isinstance(stored, dict):
            self.history = [x for x in stored.get("history", [])[-30:] if isinstance(x, dict)]
            previous = stored.get("last_result")
            if isinstance(previous, dict) and previous.get("status") in ("actief", "stoppen", "start_wacht_op_bevestiging"):
                self.last_result = {"status": "geblokkeerd", "reason": "Herstart: apparaatstatus onafhankelijk controleren",
                                    "execution_performed": False, "safe_return_required": True,
                                    "blockers": ["restart_requires_reconciliation"]}
        self._unsubs.append(self.scheduler.async_add_listener(self._queue))
        self._unsubs.append(self.store.add_listener(self._queue))
        if self.battery is not None:
            self._unsubs.append(self.battery.async_add_listener(self._queue))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(seconds=5)))
        await self.async_evaluate()

    @callback
    def _tick(self, now: datetime) -> None:
        self._queue()

    @callback
    def _queue(self) -> None:
        if self._shutdown:
            return
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self._drain(), "DOEMS execution evaluation")

    async def _drain(self) -> None:
        while self._dirty and not self._shutdown:
            self._dirty = False
            await self.async_evaluate()

    async def async_evaluate(self) -> dict[str, Any]:
        async with self._lock:
            now = dt_util.utcnow()
            scheduler = dict(self.scheduler.last_result)
            slot = scheduler.get("selected_slot")
            plan = self.store.get_plan(slot) if type(slot) is int and slot in (1, 2, 3) else None
            battery = self.battery.snapshot() if self.battery is not None else {"status": "blocked"}
            fresh = self.scheduler._sources_fresh(now, battery) if self.battery is not None else False
            # Never infer a physical acknowledgement from power measurements.
            result = evaluate_execution(now=now, scheduler=scheduler, plan=plan,
                                        battery=battery, source_fresh=fresh,
                                        previous=self.last_result)
            previous = self.last_result
            self.last_result = result
            if (previous.get("status"), previous.get("plan_identity"), previous.get("blockers")) != (
                    result.get("status"), result.get("plan_identity"), result.get("blockers")):
                self.history.append({"at": now.isoformat(), "status": result["status"],
                                     "reason": result["reason"], "plan_identity": result.get("plan_identity"),
                                     "blockers": result.get("blockers", [])})
                self.history = self.history[-30:]
                await self._storage.async_save({"last_result": result, "history": self.history})
            for listener in tuple(self._listeners):
                listener()
            return dict(result)

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
        return remove

    async def async_shutdown(self) -> None:
        self._shutdown = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._listeners.clear()
