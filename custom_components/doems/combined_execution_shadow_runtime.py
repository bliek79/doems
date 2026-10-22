"""R9 three-slot execution observer.

Read the canonical R7-selected Plan Store slot, not the 288-slot Combined
forecast. No physical battery authority is granted by this observer.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Callable

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .execution_controller import ExecutionController
from .execution_anker_adapter import AnkerExecutionAdapter


class DOEMSCombinedExecutionShadowRuntime:
    def __init__(self, hass: Any, scheduler: Any, store: Any) -> None:
        self.hass = hass
        self.scheduler = scheduler
        self.store = store
        self.adapter = AnkerExecutionAdapter(hass, {}, authority=False)
        self.controller = ExecutionController(self.adapter, authorized=lambda: False, revalidate=self._identity_current)
        self.last_result: dict[str, Any] = {"status": "startup", "physical_execution_enabled": False}
        self._unsubs: list[Callable[[], None]] = []
        self._listeners: list[Callable[[], None]] = []
        self._task: asyncio.Task | None = None
        self._dirty = False
        self._shutdown = False

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
        return remove

    def _identity_current(self, identity: tuple) -> bool:
        """Verify that R7 still selects exactly the same pending slot revision."""
        decision = self.scheduler.last_result
        slot = decision.get("selected_slot")
        if type(slot) is not int or slot not in (1, 2, 3):
            return False
        plan = self.store.get_plan(slot)
        actual = (
            slot, plan.get("lifecycle_updated_at"), plan.get("origin"),
            plan.get("planner_identity"), plan.get("planner_signature"),
            plan.get("action"), plan.get("power_w"),
            plan.get("target_soc"), plan.get("max_runtime_h"),
        )
        return (
            identity == actual
            and plan.get("lifecycle_status") == "pending"
            and decision.get("selected_lifecycle") == "pending"
            and decision.get("safety_status") == "safe"
            and not decision.get("safety_blockers")
        )

    async def async_setup(self) -> None:
        self._unsubs.append(self.scheduler.async_add_listener(self.refresh))
        self._unsubs.append(self.store.add_listener(self.refresh))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))
        self.refresh()

    def _tick(self, _now: Any) -> None:
        self.refresh()

    def refresh(self) -> None:
        if self._shutdown:
            return
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self._drain(), "DOEMS three-slot execution observer")

    async def _drain(self) -> None:
        while self._dirty and not self._shutdown:
            self._dirty = False
            try:
                self._evaluate()
            except Exception as exc:
                self.last_result = {
                    "status": "blocked", "reason": "slot_observer_error",
                    "error_type": type(exc).__name__, "physical_execution_enabled": False,
                }
            for listener in tuple(self._listeners):
                listener()

    def _evaluate(self) -> None:
        decision = dict(self.scheduler.last_result)
        slot = decision.get("selected_slot")
        if type(slot) is not int or slot not in (1, 2, 3):
            self.last_result = {
                "status": "idle", "selected_slot": None,
                "scheduler_status": decision.get("status"),
                "physical_execution_enabled": False,
            }
            return
        plan = self.store.get_plan(slot)
        blockers = list(decision.get("safety_blockers") or [])
        if plan.get("lifecycle_status") != "pending":
            blockers.append("plan_not_pending")
        if decision.get("selected_lifecycle") != plan.get("lifecycle_status"):
            blockers.append("scheduler_selection_stale")
        if plan.get("action") not in ("laden", "ontladen"):
            blockers.append("action_invalid")
        if decision.get("selected_action") != plan.get("action"):
            blockers.append("selected_action_changed")
        self.last_result = {
            "status": "blocked" if blockers else "slot_ready_observe",
            "selected_slot": slot,
            "origin": plan.get("origin"),
            "action": plan.get("action"),
            "power_w": plan.get("power_w"),
            "target_soc": plan.get("target_soc"),
            "max_runtime_h": plan.get("max_runtime_h"),
            "lifecycle_status": plan.get("lifecycle_status"),
            "planner_identity": plan.get("planner_identity"),
            "scheduler_status": decision.get("status"),
            "blockers": blockers,
            "observed_at": dt_util.utcnow().isoformat(),
            "physical_execution_enabled": False,
        }

    async def async_shutdown(self) -> None:
        self._shutdown = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._task is not None:
            await self._task
        self._listeners.clear()
