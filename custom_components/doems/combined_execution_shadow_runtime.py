"""R9 three-slot execution observer.

Read the canonical R7-selected Plan Store slot, not the 288-slot Combined
forecast. No physical battery authority is granted by this observer.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta, datetime, timezone
from copy import deepcopy
from typing import Any, Callable

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .combined_anker_bridge import CombinedAnkerBridge
from .execution_controller import ExecutionController
from .execution_anker_adapter import AnkerExecutionAdapter


class DOEMSCombinedExecutionShadowRuntime:
    def __init__(self, hass: Any, scheduler: Any, store: Any, *, entities=None, authority=False, planner=None, battery=None) -> None:
        self.hass = hass
        self.scheduler = scheduler
        self.store = store
        self._authority = bool(authority)
        self._combined_bridge = None
        self._combined_last_result: dict[str, Any] = {"bridge": "startup", "physical_execution_enabled": False}
        self.adapter = AnkerExecutionAdapter(hass, entities or {}, authority=self._authority)
        self.controller = ExecutionController(self.adapter, authorized=lambda: self._authority, revalidate=self._identity_current)
        if planner is not None:
            self._combined_bridge = CombinedAnkerBridge(
                planner, self.adapter, battery=battery, authority=False,
                exclusive=False, controller=self.controller,
            )
        self._active_plan = None
        self._active_slot = None
        self._started = set()
        self.last_result: dict[str, Any] = {"status": "startup", "physical_execution_enabled": False}
        self._unsubs: list[Callable[[], None]] = []
        self._listeners: list[Callable[[], None]] = []
        self._task: asyncio.Task | None = None
        self._dirty = False
        self._shutdown = False
        self._restart_reconciled = False
        self._last_stop_blockers = []

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
            and self._authority
            and plan.get("lifecycle_status") in ("pending", "actief")
            and (plan.get("lifecycle_status") == "actief" or decision.get("selected_lifecycle") == "pending")
            and (plan.get("lifecycle_status") == "actief" or decision.get("safety_status") == "safe")
            and (plan.get("lifecycle_status") == "actief" or not decision.get("safety_blockers"))
            and self.adapter.authority
            and all(self.adapter.entities.get(key) for key in
                    ("operating_mode", "action_direction", "power_setpoint"))
        )

    async def async_setup(self) -> None:
        self._unsubs.append(self.scheduler.async_add_listener(self.refresh))
        self._unsubs.append(self.store.add_listener(self.refresh))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(seconds=5)))
        self.refresh()

    def _tick(self, _now: Any) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Thread-safe entry point for scheduler/store notifications."""
        self.hass.loop.call_soon_threadsafe(self._refresh_on_loop)

    @callback
    def _refresh_on_loop(self) -> None:
        """Only the event loop may mutate the observer task and dirty flag."""
        if self._shutdown:
            return
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self._drain(), "DOEMS three-slot execution observer")

    async def _drain(self) -> None:
        while self._dirty and not self._shutdown:
            self._dirty = False
            try:
                await self._evaluate()
            except Exception as exc:
                self.last_result = {
                    "status": "blocked", "reason": "slot_observer_error",
                    "error_type": type(exc).__name__, "physical_execution_enabled": False,
                }
            for listener in tuple(self._listeners):
                try:
                    listener()
                except Exception:
                    # A faulty UI listener must not terminate the observer drain.
                    continue

    async def _evaluate(self) -> None:
        if self._combined_bridge is not None and not self._authority:
            try:
                self._combined_last_result = await self._combined_bridge.async_reconcile(dt_util.utcnow())
            except Exception as exc:
                self._combined_last_result = {
                    "bridge": "blocked", "reason": "combined_handoff_error",
                    "error_type": type(exc).__name__, "physical_execution_enabled": False,
                }
        if self._authority:
            await self._execute_or_monitor()
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
        if decision.get("safety_status") != "safe":
            blockers.append("r7_safety_not_safe")
        # Shadow mode must report planning readiness independently of
        # physical authority. Never imply that the battery is being controlled.
        planning_ready = not blockers
        if not self._authority:
            blockers.append("physical_authority_disabled")
        self.last_result = {
            "status": ("slot_ready_observe" if planning_ready else "blocked"),
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
            "physical_execution_enabled": bool(self.controller.session),
            "execution_authorized": self._authority,
            "reconciliation_required": self.controller.reconciliation_required,
            "last_stop_blockers": list(self._last_stop_blockers),
            "combined_handoff": deepcopy(self._combined_last_result),
        }

    def _identity(self, slot, plan):
        return (
            slot, plan.get("lifecycle_updated_at"), plan.get("origin"),
            plan.get("planner_identity"), plan.get("planner_signature"),
            plan.get("action"), plan.get("power_w"),
            plan.get("target_soc"), plan.get("max_runtime_h"),
        )

    async def _execute_or_monitor(self) -> None:
        """Use the one existing controller for both Manual and Automatic slots."""
        now = dt_util.utcnow()
        if not self._restart_reconciled:
            mode = self.adapter._state("operating_mode")
            if mode is None or mode not in ("self_consumption", "third_party_control"):
                return
            if mode == "third_party_control":
                self.controller.require_restart_reconciliation()
                await self.controller.stop()
                self._restart_reconciled = True
                return
            self._restart_reconciled = True
        if self.controller.session is not None or self.controller.reconciliation_required:
            session = self.controller.session
            snapshot = self.scheduler.battery.snapshot() if self.scheduler.battery else {}
            slot = self._active_slot
            plan = self.store.get_plan(slot) if slot in (1, 2, 3) else {}
            same_plan = bool(
                session and self._active_plan
                and plan.get("lifecycle_status") == "actief"
                and all(plan.get(key) == self._active_plan.get(key)
                        for key in ("origin", "planner_identity", "planner_signature",
                                    "action", "power_w", "target_soc", "max_runtime_h"))
            )
            soc = snapshot.get("soc_percent")
            try:
                soc = float(soc)
            except (TypeError, ValueError):
                soc = None
            try:
                outcome = await self.controller.monitor(
                    now=now, soc_percent=soc,
                    sources_fresh=self.scheduler._sources_fresh(now, snapshot),
                    controller_exclusive=self._authority,
                    command_acknowledged=bool(session and
                        self.adapter._power_matches(session["power_w"]) and
                        self.adapter._state("operating_mode") == "third_party_control"),
                    plan_identity_matches=same_plan,
                    safety_clear=same_plan and snapshot.get("status") == "ready",
                )
                if outcome.get("decision") == "stop":
                    blockers = list(outcome.get("blockers") or [])
                    self._last_stop_blockers = blockers
                    normal = bool(blockers) and all(
                        b in ("target_reached", "runtime_elapsed") for b in blockers
                    )
                    if same_plan:
                        await self.store.async_mark_lifecycle(
                            slot, "voltooid" if normal else "fout",
                            "execution_completed" if normal else "execution_safety_stopped",
                            expected_plan=plan)
                    self._active_plan = None
                    self._active_slot = None
            except Exception:
                # Keep the controller reconciliation fence raised on uncertain stop.
                self.controller.reconciliation_required = True
            return

        decision = self.scheduler.last_result
        slot = decision.get("selected_slot")
        if type(slot) is not int or slot not in (1, 2, 3):
            return
        plan = self.store.get_plan(slot)
        identity = self._identity(slot, plan)
        if identity in self._started or not self._identity_current(identity):
            return
        power = plan.get("power_w")
        target = plan.get("target_soc")
        runtime = plan.get("max_runtime_h")
        if type(power) not in (int, float) or not 100 <= power <= 3500 or int(power) != power:
            return
        power = int(power)
        if type(target) not in (int, float) or not 5 <= target <= 100:
            return
        if type(runtime) not in (int, float) or not 0.25 <= runtime <= 12:
            return
        self._started.add(identity)
        try:
            await self.controller.start(
                identity=identity, action=plan["action"], power_w=power,
                target_soc=target, max_runtime_h=runtime, now=now)
            if await self.store.async_mark_lifecycle(
                slot, "actief", "r7_execution_started", expected_plan=plan):
                self._active_slot = slot
                self._active_plan = self.store.get_plan(slot)
            else:
                await self.controller.stop()
        except Exception:
            # Never retry an ambiguous start; the controller owns safe cleanup.
            if not self.controller.reconciliation_required:
                await self.store.async_mark_lifecycle(
                    slot, "fout", "execution_start_failed", expected_plan=plan)

    async def async_shutdown(self) -> None:
        self._shutdown = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._task is not None:
            await self._task
        if self._authority and (self.controller.session is not None or self.controller.reconciliation_required):
            await self.controller.stop()
        self._listeners.clear()
