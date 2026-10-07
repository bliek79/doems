"""Timer/runtime bridge for DOEMS R4 manual plan lifecycle expiry."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .manual_plan_lifecycle_model import next_manual_expiry_deadline
from .manual_plan_model import PLAN_SLOT_COUNT
from .manual_plan_store import DOEMSManualPlanStore


class DOEMSManualPlanLifecycle:
    """Release only valid expired manual pending plans.

    This runtime owns time/lifecycle cleanup only. It has no Scheduler,
    automatic planning, Safety, Prestart or physical battery authority.
    """

    def __init__(self, hass: HomeAssistant, store: DOEMSManualPlanStore) -> None:
        self.hass = hass
        self.store = store
        self._listeners: set[Callable[[], None]] = set()
        self._remove_store_listener: Callable[[], None] | None = None
        self._remove_timer: Callable[[], None] | None = None
        self._evaluation_running = False
        self._last_result: dict[str, Any] = {
            "changed": False,
            "released_slots": [],
            "blockers": [],
            "events": [],
            "evaluated_at": None,
        }
        self._next_expiry_at: str | None = None
        self._next_expiry_slot: int | None = None

    async def async_setup(self) -> None:
        await self.async_evaluate()
        self._remove_store_listener = self.store.add_listener(
            self._handle_store_change
        )
        self._schedule_next_expiry()

    async def async_shutdown(self) -> None:
        if self._remove_store_listener is not None:
            self._remove_store_listener()
            self._remove_store_listener = None
        self._cancel_timer()
        self._listeners.clear()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)

        @callback
        def _remove() -> None:
            self._listeners.discard(listener)

        return _remove

    @callback
    def _handle_store_change(self) -> None:
        self.hass.async_create_task(self.async_evaluate())

    async def async_evaluate(self, now: datetime | None = None) -> dict[str, Any]:
        if self._evaluation_running:
            return dict(self._last_result)

        self._evaluation_running = True
        try:
            reference = now or dt_util.now()
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            result = await self.store.async_release_expired_manual_plans(
                now=reference
            )
            result["evaluated_at"] = reference.isoformat()
            self._last_result = result
        finally:
            self._evaluation_running = False

        self._schedule_next_expiry()
        self._notify()
        return dict(self._last_result)

    def snapshot(self) -> dict[str, Any]:
        blockers = list(self._last_result.get("blockers") or [])
        return {
            "status": "blocked" if blockers else "ready",
            "blockers": blockers,
            "last_evaluated_at": self._last_result.get("evaluated_at"),
            "last_changed": bool(self._last_result.get("changed")),
            "last_released_slots": list(
                self._last_result.get("released_slots") or []
            ),
            "last_events": list(self._last_result.get("events") or []),
            "next_expiry_at": self._next_expiry_at,
            "next_expiry_slot": self._next_expiry_slot,
            "last_terminal_events": self.store.last_terminal_events(),
            "manual_only": True,
            "scheduler_active": False,
            "automatic_planner_active": False,
            "physical_execution_authority": False,
        }

    def _schedule_next_expiry(self) -> None:
        self._cancel_timer()
        now = dt_util.now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

        plans = [
            self.store.get_plan(slot)
            for slot in range(1, PLAN_SLOT_COUNT + 1)
        ]
        next_expiry = next_manual_expiry_deadline(plans, now=now)
        deadline = next_expiry.get("deadline")
        slot = next_expiry.get("slot")
        if not isinstance(deadline, datetime) or not isinstance(slot, int):
            self._next_expiry_at = None
            self._next_expiry_slot = None
            return

        # Expiry is strictly after the exact window end, matching the proven
        # old EMS automatic-slot lifecycle boundary.
        fire_at = deadline + timedelta(seconds=1)
        if fire_at <= now:
            fire_at = now + timedelta(seconds=1)

        self._next_expiry_at = deadline.isoformat()
        self._next_expiry_slot = slot
        self._remove_timer = async_track_point_in_utc_time(
            self.hass,
            self._handle_expiry_timer,
            fire_at.astimezone(timezone.utc),
        )

    @callback
    def _handle_expiry_timer(self, now: datetime) -> None:
        self._remove_timer = None
        self.hass.async_create_task(self.async_evaluate(now=now))

    def _cancel_timer(self) -> None:
        if self._remove_timer is not None:
            self._remove_timer()
            self._remove_timer = None

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()
