"""Persistent manual Plan Store for the DOEMS reset line."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .manual_plan_lifecycle_model import (
    MANUAL_EXPIRY_REASON,
    MANUAL_RELEASE_REASON,
    evaluate_manual_plan_expiry,
)
from .manual_plan_model import (
    CONTROL_FIELDS,
    LIFECYCLE_STATUSES,
    PLAN_SLOT_COUNT,
    manual_plan_status,
    new_manual_plan,
    validate_manual_plan,
)

STORAGE_VERSION = 1
TERMINAL_EVENT_LIMIT = 12


class DOEMSManualPlanStore:
    """Three persistent manual-only plan slots.

    R2 owns storage and editing only. It has no Scheduler, automatic planner,
    SOC projection or physical battery authority.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.storage_key = f"doems.{entry_id}.manual_plans"
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            self.storage_key,
        )
        self._plans = {
            slot: new_manual_plan()
            for slot in range(1, PLAN_SLOT_COUNT + 1)
        }
        self._listeners: set[Callable[[], None]] = set()
        self._terminal_events: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        raw_plans = stored.get("plans")
        if not isinstance(raw_plans, dict):
            return

        raw_events = stored.get("terminal_events")
        if isinstance(raw_events, list):
            self._terminal_events = [
                deepcopy(event)
                for event in raw_events[-TERMINAL_EVENT_LIMIT:]
                if isinstance(event, dict)
            ]

        for slot in range(1, PLAN_SLOT_COUNT + 1):
            raw = raw_plans.get(str(slot))
            if not isinstance(raw, dict):
                continue
            plan = new_manual_plan()
            for key in plan:
                if key in raw:
                    plan[key] = raw[key]
            # The reset line is manual-only. Never revive another origin from
            # persisted data.
            plan["origin"] = "manual"
            self._plans[slot] = plan

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)

        def _remove() -> None:
            self._listeners.discard(listener)

        return _remove

    def get_plan(self, slot: int) -> dict[str, Any]:
        self._validate_slot(slot)
        return deepcopy(self._plans[slot])

    def last_terminal_events(self) -> list[dict[str, Any]]:
        """Return compact audit evidence kept outside active slots."""
        return deepcopy(self._terminal_events)

    def last_terminal_event(self, slot: int) -> dict[str, Any] | None:
        """Return the most recent terminal event for one slot."""
        self._validate_slot(slot)
        for event in reversed(self._terminal_events):
            if event.get("slot") == slot:
                return deepcopy(event)
        return None

    def get_value(self, slot: int, field: str) -> Any:
        self._validate_slot(slot)
        return self._plans[slot].get(field)

    def plan_status(self, slot: int) -> str:
        self._validate_slot(slot)
        return manual_plan_status(self._plans[slot], now=dt_util.now())

    def schedule_blockers(self, slot: int) -> list[str]:
        self._validate_slot(slot)
        plan = self._plans[slot]
        candidate = deepcopy(plan)
        candidate["execution_mode"] = "gepland"
        return validate_manual_plan(
            candidate,
            now=dt_util.now(),
            require_future_start=True,
        )

    async def async_set_value(self, slot: int, field: str, value: Any) -> None:
        self._validate_slot(slot)
        if field not in CONTROL_FIELDS:
            raise ValueError(f"Unknown plan field: {field}")

        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            value = value.isoformat()

        self._plans[slot][field] = value
        self._plans[slot]["origin"] = "manual"
        self._plans[slot]["lifecycle_status"] = "concept"
        self._plans[slot]["lifecycle_reason"] = "plan_changed"
        self._plans[slot]["lifecycle_updated_at"] = dt_util.now().isoformat()
        await self._async_save()
        self._notify()

    async def async_schedule(self, slot: int) -> None:
        self._validate_slot(slot)
        candidate = deepcopy(self._plans[slot])
        candidate["execution_mode"] = "gepland"
        blockers = validate_manual_plan(
            candidate,
            now=dt_util.now(),
            require_future_start=True,
        )
        if blockers:
            raise ValueError(",".join(blockers))

        self._plans[slot]["execution_mode"] = "gepland"
        self._plans[slot]["origin"] = "manual"
        self._plans[slot]["lifecycle_status"] = "pending"
        self._plans[slot]["lifecycle_reason"] = "scheduled_by_user"
        self._plans[slot]["lifecycle_updated_at"] = dt_util.now().isoformat()
        await self._async_save()
        self._notify()

    async def async_cancel(self, slot: int) -> None:
        self._validate_slot(slot)
        self._plans[slot]["origin"] = "manual"
        self._plans[slot]["lifecycle_status"] = "geannuleerd"
        self._plans[slot]["lifecycle_reason"] = "manual_cancel"
        self._plans[slot]["lifecycle_updated_at"] = dt_util.now().isoformat()
        await self._async_save()
        self._notify()

    async def async_clear(self, slot: int) -> None:
        self._validate_slot(slot)
        cleared = new_manual_plan()
        cleared["lifecycle_reason"] = "manual_clear"
        cleared["lifecycle_updated_at"] = dt_util.now().isoformat()
        self._plans[slot] = cleared
        await self._async_save()
        self._notify()

    async def async_release_expired_manual_plans(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Release valid manual pending plans after their complete start window.

        The active slot becomes immediately reusable. A compact audit event is
        persisted outside the active slot so expiry evidence is retained without
        keeping one of the three planning slots occupied.
        """
        reference = now or dt_util.now()
        if reference.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        blockers: list[str] = []
        events: list[dict[str, Any]] = []
        released_slots: list[int] = []

        for slot in range(1, PLAN_SLOT_COUNT + 1):
            current = self._plans[slot]
            evaluation = evaluate_manual_plan_expiry(
                current,
                now=reference,
                slot=slot,
            )
            blockers.extend(str(value) for value in evaluation.get("blockers", []))
            if evaluation.get("expired") is not True:
                continue

            event = {
                "slot": slot,
                "status": "verlopen",
                "reason": MANUAL_EXPIRY_REASON,
                "released_reason": MANUAL_RELEASE_REASON,
                "expired_at": reference.isoformat(),
                "start_time": current.get("start_time"),
                "start_window_end": evaluation.get("window_end"),
                "action": current.get("action"),
                "execution_mode": current.get("execution_mode"),
                "power_w": current.get("power_w"),
                "target_soc": current.get("target_soc"),
                "max_runtime_h": current.get("max_runtime_h"),
                "max_start_delay_min": current.get("max_start_delay_min"),
                "origin": "manual",
            }
            events.append(event)

            cleared = new_manual_plan()
            cleared["lifecycle_reason"] = MANUAL_RELEASE_REASON
            cleared["lifecycle_updated_at"] = reference.isoformat()
            self._plans[slot] = cleared
            released_slots.append(slot)

        if released_slots:
            self._terminal_events.extend(events)
            self._terminal_events = self._terminal_events[-TERMINAL_EVENT_LIMIT:]
            await self._async_save()
            self._notify()

        return {
            "changed": bool(released_slots),
            "released_slots": released_slots,
            "blockers": sorted(set(blockers)),
            "events": deepcopy(events),
        }

    async def async_mark_lifecycle(
        self,
        slot: int,
        status: str,
        reason: str | None = None,
    ) -> None:
        """Lifecycle primitive reserved for later validated layers/tests."""
        self._validate_slot(slot)
        if status not in LIFECYCLE_STATUSES:
            raise ValueError(f"Unknown lifecycle status: {status}")
        self._plans[slot]["lifecycle_status"] = status
        self._plans[slot]["lifecycle_reason"] = reason
        self._plans[slot]["lifecycle_updated_at"] = dt_util.now().isoformat()
        await self._async_save()
        self._notify()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "schema_version": STORAGE_VERSION,
                "plans": {
                    str(slot): deepcopy(plan)
                    for slot, plan in self._plans.items()
                },
                "terminal_events": deepcopy(
                    self._terminal_events[-TERMINAL_EVENT_LIMIT:]
                ),
            }
        )

    def _validate_slot(self, slot: int) -> None:
        if slot not in self._plans:
            raise ValueError(f"Unknown plan slot: {slot}")

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()
