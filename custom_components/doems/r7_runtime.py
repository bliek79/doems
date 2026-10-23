"""R7 event/timer orchestration. No actuator or battery-mode API is imported."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .r7_model import AUTO_ORIGIN, _num, _time, evaluate_r7
from .manual_soc_projection_model import MIN_SOC_PERCENT


class DOEMSR7Scheduler:
    """Scheduler, Safety and Prestart gate on the existing R6 three-slot store."""

    def __init__(self, hass: HomeAssistant, planner, bridge, store, battery) -> None:
        self.hass, self.planner, self.bridge = hass, planner, bridge
        self.store, self.battery = store, battery
        self._lock = asyncio.Lock()
        self._subscriptions: list[Callable[[], None]] = []
        self._listeners: list[Callable[[], None]] = []
        self._timer_unsub: Callable[[], None] | None = None
        self._task: asyncio.Task | None = None
        self._dirty = False
        self._shutdown = False
        self.last_result: dict[str, Any] = {"status": "startup", "physical_execution_enabled": False}
        self.last_promotion: dict[str, Any] | None = None

    async def async_setup(self) -> None:
        self._subscriptions.append(self.planner.async_add_listener(self._queue_evaluate))
        self._subscriptions.append(self.store.add_listener(self._queue_evaluate))
        if self.battery is not None:
            self._subscriptions.append(self.battery.async_add_listener(self._queue_evaluate))
        await self.async_evaluate()

    async def async_shutdown(self) -> None:
        self._shutdown = True
        self._cancel_timer()
        for remove in self._subscriptions:
            remove()
        self._subscriptions.clear()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._listeners.clear()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def _queue_evaluate(self) -> None:
        """Accept listener notifications from any thread."""
        self.hass.loop.call_soon_threadsafe(self._queue_evaluate_on_loop)

    @callback
    def _queue_evaluate_on_loop(self) -> None:
        if self._shutdown:
            return
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self._drain(), "DOEMS R7 Scheduler Safety Prestart")

    async def _drain(self) -> None:
        while self._dirty and not self._shutdown:
            self._dirty = False
            await self.async_evaluate()

    @callback
    def _on_timer(self, now: datetime) -> None:
        self._timer_unsub = None
        self._queue_evaluate()

    def _cancel_timer(self) -> None:
        if self._timer_unsub is not None:
            self._timer_unsub()
            self._timer_unsub = None

    def _schedule(self, result: dict[str, Any]) -> None:
        self._cancel_timer()
        when = _time(result.get("next_wake_at"))
        if when is None or self._shutdown:
            return
        current = dt_util.utcnow()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if when <= current:
            when = current + timedelta(seconds=1)
        self._timer_unsub = async_track_point_in_utc_time(self.hass, self._on_timer, when)

    def _sources_fresh(self, now: datetime, battery_snapshot: dict[str, Any]) -> bool:
        if self.battery is None:
            return False
        sources = battery_snapshot.get("source_entities") or {}
        if not sources or any(not value for value in sources.values()):
            return False
        for entity_id in sources.values():
            state = self.hass.states.get(entity_id)
            if state is None:
                return False
            reported = getattr(state, "last_reported", None) or getattr(state, "last_updated", None)
            if not isinstance(reported, datetime) or reported.tzinfo is None:
                return False
            age = now.astimezone(timezone.utc) - reported.astimezone(timezone.utc)
            if age > timedelta(hours=2) or age < -timedelta(minutes=5):
                return False
        return True

    def _manual_safety_limits(self) -> dict[str, float]:
        """Independent configured hard limits; invalid settings fail closed in R7."""
        try:
            settings = self.planner._settings()
            charge = _num(settings.get("max_charge_power_w"))
            discharge = _num(settings.get("max_discharge_power_w"))
            reserve = _num(settings.get("software_reserve_percent"))
            if (charge is None or not 100 <= charge <= 100000
                    or discharge is None or not 100 <= discharge <= 100000
                    or reserve is None or not 0 <= reserve <= 30
                    or MIN_SOC_PERCENT + reserve > 100):
                return {}
            return {
                "max_charge_power_w": charge,
                "max_discharge_power_w": discharge,
                "planner_floor_soc_percent": MIN_SOC_PERCENT + reserve,
            }
        except (AttributeError, TypeError, ValueError, OverflowError):
            return {}

    async def async_evaluate(self, *, now: datetime | None = None) -> dict[str, Any]:
        if self._shutdown:
            return dict(self.last_result)
        async with self._lock:
            reference = now or dt_util.now()
            if reference.tzinfo is None:
                raise ValueError("now must be timezone-aware")
            clock = reference.astimezone(timezone.utc)
            plans = {i: self.store.get_plan(i) for i in (1, 2, 3)}
            due_auto = any(
                plan.get("origin") == AUTO_ORIGIN
                and plan.get("lifecycle_status") == "concept"
                and (start := _time(plan.get("start_time"))) is not None
                and (margin := _num(plan.get("max_start_delay_min"))) is not None
                and start <= clock <= start + timedelta(minutes=margin)
                for plan in plans.values()
            )
            if due_auto:
                # R6 owns expiry and frozen plan revisions; evaluate its full
                # current-generation gate before allowing any R7 promotion.
                await self.bridge.async_evaluate(now=reference)
                plans = {i: self.store.get_plan(i) for i in (1, 2, 3)}
            bundle = self.planner.bundle_snapshot()
            battery = self.battery.snapshot() if self.battery else {"status": "blocked"}
            manual_limits = self._manual_safety_limits()
            result = evaluate_r7(
                now=reference, plans=plans, bundle=bundle, battery=battery,
                bridge_ready=self.bridge.last_result.get("status") == "ready",
                planner_generation=self.planner._generation,
                source_fresh=self._sources_fresh(reference, battery),
                manual_limits=manual_limits,
            )
            if result["can_promote"] and self.planner.bundle_snapshot() is bundle:
                slot = result["selected_slot"]
                selected = plans[slot]
                changed = await self.store.async_promote_automatic_plan(
                    slot, expected_identity=selected["planner_identity"],
                    expected_signature=selected["planner_signature"],
                    expected_updated_at=selected.get("lifecycle_updated_at"),
                    gate_approved=True, now=reference,
                )
                if changed:
                    self.last_promotion = {
                        "slot": slot, "at": reference.isoformat(),
                        "planner_identity": selected["planner_identity"],
                    }
                    result = evaluate_r7(
                        now=reference,
                        plans={i: self.store.get_plan(i) for i in (1, 2, 3)},
                        bundle=self.planner.bundle_snapshot(), battery=battery,
                        bridge_ready=self.bridge.last_result.get("status") == "ready",
                        planner_generation=self.planner._generation,
                        source_fresh=self._sources_fresh(reference, battery),
                        manual_limits=manual_limits,
                    )
            result["last_promotion"] = self.last_promotion
            self.last_result = result
            self._schedule(result)
            for listener in tuple(self._listeners):
                listener()
            return dict(result)
