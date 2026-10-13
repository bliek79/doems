"""Persistent manual Plan Store for the DOEMS reset line."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta, timezone
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
AUTO_ORIGIN = "automatic_72h_planner"
AUTO_METADATA_FIELDS = (
    "purpose", "planned_end_time", "planned_energy_kwh",
    "planner_identity", "planner_signature", "price_sources", "all_prices_known",
)


def _aware_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _drop_auto_metadata(plan: dict[str, Any]) -> None:
    for field in AUTO_METADATA_FIELDS:
        plan.pop(field, None)


def _automatic_expiry(plan: dict[str, Any]) -> datetime | None:
    start = _aware_utc(plan.get("start_time"))
    if start is None:
        return None
    try:
        delay = float(plan.get("max_start_delay_min", 10.0))
    except (TypeError, ValueError):
        return None
    if not 1.0 <= delay <= 120.0:
        return None
    return start + timedelta(minutes=delay)




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
        self._manual_listeners: set[Callable[[], None]] = set()
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
            # Legacy slots remain Manual; only genuine R6-owned proposals
            # retain automatic provenance and identity after reload.
            if raw.get("origin") == AUTO_ORIGIN:
                plan["origin"] = AUTO_ORIGIN
                for field in AUTO_METADATA_FIELDS:
                    if field in raw:
                        plan[field] = deepcopy(raw[field])
            else:
                plan["origin"] = "manual"
            self._plans[slot] = plan

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)

        def _remove() -> None:
            self._listeners.discard(listener)

        return _remove

    def add_manual_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Notify R2-R5 computation only when a user changes Manual plans."""
        self._manual_listeners.add(listener)

        def _remove() -> None:
            self._manual_listeners.discard(listener)

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
        _drop_auto_metadata(self._plans[slot])
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
        _drop_auto_metadata(self._plans[slot])
        self._plans[slot]["lifecycle_status"] = "pending"
        self._plans[slot]["lifecycle_reason"] = "scheduled_by_user"
        self._plans[slot]["lifecycle_updated_at"] = dt_util.now().isoformat()
        await self._async_save()
        self._notify()

    async def async_cancel(self, slot: int) -> None:
        self._validate_slot(slot)
        self._plans[slot]["origin"] = "manual"
        _drop_auto_metadata(self._plans[slot])
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


    async def async_promote_automatic_plan(
        self,
        slot: int,
        *,
        expected_identity: str,
        expected_signature: str,
        expected_updated_at: str | None,
        gate_approved: bool,
        now: datetime | None = None,
    ) -> bool:
        """R7: atomic guarded *software-only* concept -> pending transition.

        R7 owns the prior Safety/Prestart decision. This method additionally
        guards slot ownership/revision and the exact start window. It must never
        call a battery service, start a plan, or notify Manual/R5 listeners.
        """
        self._validate_slot(slot)
        reference = now or dt_util.now()
        if reference.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        current = self._plans[slot]
        start = _aware_utc(current.get("start_time"))
        deadline = _automatic_expiry(current)
        clock = reference.astimezone(timezone.utc)
        if (
            gate_approved is not True
            or current.get("origin") != AUTO_ORIGIN
            or current.get("lifecycle_status") != "concept"
            or current.get("execution_mode") != "gepland"
            or current.get("action") not in {"laden", "ontladen"}
            or not expected_identity
            or current.get("planner_identity") != expected_identity
            or not expected_signature
            or current.get("planner_signature") != expected_signature
            or current.get("lifecycle_updated_at") != expected_updated_at
            or start is None
            or deadline is None
            or not start <= clock <= deadline
        ):
            return False
        # No await before the ownership/window check and in-memory mutation:
        # a concurrent Manual or R6 task cannot claim this slot between them.
        current["lifecycle_status"] = "pending"
        current["lifecycle_reason"] = "r7_scheduler_prestart_safe"
        current["lifecycle_updated_at"] = reference.isoformat()
        await self._async_save()
        self._notify_automatic()
        return True

    async def async_release_expired_automatic_plans(
        self, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """R6: release automatic proposals after their *complete* start window."""
        reference = now or dt_util.now()
        if reference.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        clock = reference.astimezone(timezone.utc)
        events: list[dict[str, Any]] = []
        released: list[int] = []
        for slot in range(1, PLAN_SLOT_COUNT + 1):
            current = self._plans[slot]
            if current.get("origin") != AUTO_ORIGIN:
                continue
            if current.get("lifecycle_status") not in {"concept", "pending"}:
                continue
            deadline = _automatic_expiry(current)
            if deadline is None or clock <= deadline:
                continue
            events.append({
                "slot": slot,
                "status": "verlopen",
                "reason": "automatic_start_window_expired",
                "released_reason": "automatic_expired_released",
                "expired_at": reference.isoformat(),
                "start_time": current.get("start_time"),
                "start_window_end": deadline.isoformat(),
                "action": current.get("action"),
                "origin": AUTO_ORIGIN,
                "planner_identity": current.get("planner_identity"),
            })
            cleared = new_manual_plan()
            cleared["lifecycle_reason"] = "automatic_expired_released"
            cleared["lifecycle_updated_at"] = reference.isoformat()
            self._plans[slot] = cleared
            released.append(slot)
        if released:
            self._terminal_events.extend(events)
            self._terminal_events = self._terminal_events[-TERMINAL_EVENT_LIMIT:]
            await self._async_save()
            self._notify_automatic()
        return {"changed": bool(released), "released_slots": released, "events": deepcopy(events)}

    async def async_sync_automatic_plans(
        self, proposals: list[dict[str, Any]], *, now: datetime | None = None
    ) -> dict[str, Any]:
        """R6: reconcile proposals atomically into the three existing slots.

        Never alter a user-owned Manual concept/pending/active slot. After the
        first instant of the start window, an auto proposal is frozen until
        expiry. There is no scheduler handoff or physical execution here.
        """
        reference = now or dt_util.now()
        if reference.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        clock = reference.astimezone(timezone.utc)
        current = {slot: deepcopy(plan) for slot, plan in self._plans.items()}
        staged = {slot: deepcopy(plan) for slot, plan in current.items()}
        occupied: set[int] = set()
        identities: set[str] = set()
        written: list[int] = []
        cleared: list[int] = []
        skipped: list[str] = []

        def reusable(slot: int) -> bool:
            plan = staged[slot]
            lifecycle = str(plan.get("lifecycle_status") or "concept").lower()
            if plan.get("origin") == AUTO_ORIGIN:
                start = _aware_utc(plan.get("start_time"))
                return lifecycle == "concept" and start is not None and clock < start
            if lifecycle in {"geannuleerd", "voltooid", "fout", "verlopen"}:
                return True
            return (
                plan.get("action") in (None, "geen")
                and lifecycle == "concept"
                and plan.get("lifecycle_reason") in (None, "manual_clear", "automatic_expired_released")
            )

        frozen: dict[int, dict[str, Any]] = {}
        for slot, plan in current.items():
            if plan.get("origin") != AUTO_ORIGIN:
                continue
            if plan.get("lifecycle_status") not in {"concept", "pending", "actief"}:
                continue
            start = _aware_utc(plan.get("start_time"))
            deadline = _automatic_expiry(plan)
            if start is not None and clock >= start and (deadline is None or clock <= deadline):
                frozen[slot] = plan
                occupied.add(slot)
                if plan.get("planner_identity"):
                    identities.add(str(plan["planner_identity"]))

        # Reserve slots holding *future* proposals with stable identities
        # before placing new candidates. A newly available earlier candidate
        # must not shuffle still-valid existing automatic assignments.
        wanted_ids = {
            str(item.get("planner_identity"))
            for item in proposals
            if item.get("origin") == AUTO_ORIGIN
            and item.get("planner_identity")
            and (_aware_utc(item.get("start_time")) or clock) > clock
        }
        reserved_matches: set[int] = {
            slot for slot in range(1, PLAN_SLOT_COUNT + 1)
            if current[slot].get("origin") == AUTO_ORIGIN
            and current[slot].get("planner_identity") in wanted_ids
            and reusable(slot)
        }

        for candidate in proposals:
            identity = candidate.get("planner_identity")
            start = _aware_utc(candidate.get("start_time"))
            end = _aware_utc(candidate.get("planned_end_time"))
            if not identity or identity in identities or start is None or end is None or start <= clock or end <= start:
                skipped.append(str(identity or "invalid_candidate"))
                continue
            if candidate.get("origin") != AUTO_ORIGIN or candidate.get("action") not in {"laden", "ontladen"}:
                skipped.append(str(identity))
                continue
            # Do not duplicate the same-direction action while an already
            # started automatic plan still covers its future time window.
            duplicate_frozen = False
            for existing in frozen.values():
                frozen_end = _aware_utc(existing.get("planned_end_time"))
                if existing.get("action") == candidate.get("action") and frozen_end is not None and start < frozen_end:
                    duplicate_frozen = True
                    break
            if duplicate_frozen:
                skipped.append(str(identity))
                continue

            selected = next((
                slot for slot in range(1, PLAN_SLOT_COUNT + 1)
                if slot not in occupied
                and current[slot].get("origin") == AUTO_ORIGIN
                and current[slot].get("planner_identity") == identity
                and reusable(slot)
            ), None)
            if selected is None:
                selected = next((
                    slot for slot in range(1, PLAN_SLOT_COUNT + 1)
                    if slot not in occupied
                    and slot not in reserved_matches
                    and reusable(slot)
                ), None)
            if selected is None:
                skipped.append(str(identity))
                continue
            occupied.add(selected)
            identities.add(str(identity))
            old = staged[selected]
            if old.get("origin") == AUTO_ORIGIN and old.get("planner_signature") == candidate.get("planner_signature"):
                continue
            plan = new_manual_plan()
            for field in CONTROL_FIELDS:
                if field in candidate:
                    plan[field] = deepcopy(candidate[field])
            for field in AUTO_METADATA_FIELDS:
                if field in candidate:
                    plan[field] = deepcopy(candidate[field])
            plan["origin"] = AUTO_ORIGIN
            plan["lifecycle_status"] = "concept"
            plan["lifecycle_reason"] = "automatic_proposal_written"
            plan["lifecycle_updated_at"] = reference.isoformat()
            staged[selected] = plan
            written.append(selected)

        for slot in range(1, PLAN_SLOT_COUNT + 1):
            if slot in occupied or staged[slot].get("origin") != AUTO_ORIGIN or not reusable(slot):
                continue
            blank = new_manual_plan()
            blank["lifecycle_reason"] = "automatic_proposal_cleared"
            blank["lifecycle_updated_at"] = reference.isoformat()
            staged[slot] = blank
            cleared.append(slot)

        if written or cleared:
            # Ownership checked again in the same event-loop turn, before the
            # full staged state is installed. One persistent save per revision.
            for slot in written + cleared:
                if self._plans[slot] != current[slot]:
                    return {"changed": False, "blocked": "slot_changed_during_sync"}
            self._plans = staged
            await self._async_save()
            self._notify_automatic()
        return {
            "changed": bool(written or cleared),
            "written_slots": written,
            "cleared_slots": cleared,
            "skipped_identities": skipped,
        }

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
        for listener in tuple(self._manual_listeners):
            listener()

    def _notify_automatic(self) -> None:
        """Refresh slot-facing entities only; never restart R5 calculations."""
        for listener in tuple(self._listeners):
            listener()
