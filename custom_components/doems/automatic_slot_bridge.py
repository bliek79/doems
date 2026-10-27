"""R6 rolling three-slot bridge: R5 observer output -> Plan Store proposals.

No scheduler, prestart gate, execution service or physical battery authority.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .automatic_slot_bridge_model import build_automatic_slot_proposals
from .automatic_combined_planner import DOEMSPlannerManager
from .manual_plan_store import (
    AUTO_ORIGIN,
    DOEMSManualPlanStore,
    _automatic_expiry,
)


class DOEMSAutoSlotBridge:
    """One lightweight slot reconciler attached to an existing R5 manager."""

    def __init__(
        self,
        hass: HomeAssistant,
        planner: DOEMSPlannerManager,
        store: DOEMSManualPlanStore,
    ) -> None:
        self.hass = hass
        self.planner = planner
        self.store = store
        self._lock = asyncio.Lock()
        self._unsubs: list[Callable[[], None]] = []
        self._timer_unsub: Callable[[], None] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._manual_serial = 0
        self._manual_pending = False
        self._manual_required_revision = 0
        self._shutdown = False
        self._published_bundle = None
        self._published_serial = None
        self._published_proposals: tuple[dict[str, Any], ...] = ()
        self.last_result: dict[str, Any] = {"status": "startup"}

    async def async_setup(self) -> None:
        self._unsubs.append(
            self.planner.async_add_listener(self._planner_updated)
        )
        self._unsubs.append(
            self.store.add_manual_listener(self._manual_changed)
        )
        await self.async_evaluate()

    async def async_shutdown(self) -> None:
        self._published_bundle = None
        self._published_proposals = ()
        self._shutdown = True
        self._cancel_timer()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self._tasks.clear()

    @callback
    def _queue_evaluate(self) -> None:
        if self._shutdown:
            return
        task = self.hass.async_create_task(
            self.async_evaluate(), "DOEMS R6 automatic slots"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @callback
    def _planner_updated(self) -> None:
        self._queue_evaluate()

    @callback
    def _manual_changed(self) -> None:
        self._manual_serial += 1
        self._published_bundle = None
        self._published_proposals = ()
        # A user edit immediately invalidates the previously published
        # Combined for R6 writes, even before the R5 replan task is scheduled.
        self._manual_pending = True
        self._manual_required_revision = max(
            self._manual_required_revision, self.planner._manual_revision + 1
        )
        # A new Combined publication triggers the actual slot revision.
        # Only repair expiry scheduling here, never use stale Combined rows.
        self._arm_expiry_timer()

    @callback
    def _handle_expiry(self, now: datetime) -> None:
        self._timer_unsub = None
        self._queue_evaluate()

    def _cancel_timer(self) -> None:
        if self._timer_unsub is not None:
            self._timer_unsub()
            self._timer_unsub = None

    def _arm_expiry_timer(self) -> None:
        self._cancel_timer()
        if self._shutdown:
            return
        now = dt_util.utcnow()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        deadlines = [
            _automatic_expiry(self.store.get_plan(slot))
            for slot in (1, 2, 3)
            if self.store.get_plan(slot).get("origin") == AUTO_ORIGIN
            and self.store.get_plan(slot).get("lifecycle_status") in {"concept", "pending"}
        ]
        deadlines = [deadline for deadline in deadlines if deadline is not None]
        if not deadlines:
            return
        deadline = min(deadlines) + timedelta(seconds=1)
        if deadline <= now:
            deadline = now + timedelta(seconds=1)
        self._timer_unsub = async_track_point_in_utc_time(
            self.hass, self._handle_expiry, deadline.astimezone(timezone.utc)
        )

    def verified_published_candidate(self, plan: dict[str, Any]) -> dict[str, Any] | None:
        """Read-only R6 witness; never infer candidates from legacy planner."""
        bundle = self.planner.bundle_snapshot()
        if (self._shutdown or self._manual_pending
                or self.last_result.get("status") != "ready"
                or bundle is not self._published_bundle
                or self._published_serial != self._manual_serial
                or bundle.get("planner_published_generation") != self.planner._generation):
            return None
        identity = plan.get("planner_identity")
        revision = plan.get("planner_signature")
        matches = [
            item for item in self._published_proposals
            if identity and revision and
            item.get("planner_identity") == identity
        ]
        if len(matches) != 1:
            return None
        candidate = matches[0]
        for key in ("planner_signature", "action", "power_w", "target_soc",
                    "start_time", "planned_end_time"):
            if candidate.get(key) != plan.get(key):
                return None
        return deepcopy(candidate)

    async def async_evaluate(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Do not write proposals until both R5 stages are ready and current."""
        async with self._lock:
            if self._shutdown:
                return dict(self.last_result)
            reference = now or dt_util.now()
            if reference.tzinfo is None:
                raise ValueError("now must be timezone-aware")

            # Revoke old proof before any awaited refresh or store mutation.
            self._published_bundle = None
            self._published_proposals = ()
            # Expiry is independent of provider outages / planner validity.
            expired = await self.store.async_release_expired_automatic_plans(
                now=reference
            )
            bundle = self.planner.bundle_snapshot()
            serial = self._manual_serial
            if (
                bundle.get("status") != "ready"
                or bundle.get("valid") is not True
                or not isinstance(bundle.get("automatic"), dict)
                or not isinstance(bundle.get("combined"), dict)
                or bundle["automatic"].get("valid") is not True
                or bundle["combined"].get("valid") is not True
                or bundle["automatic"].get("native_slot_count") != 288
                or bundle["combined"].get("native_slot_count") != 288
                or bundle.get("planner_published_generation")
                   != self.planner._generation
                or (
                    self._manual_pending
                    and int(bundle.get("planner_manual_revision") or -1)
                        < self._manual_required_revision
                )
            ):
                self.last_result = {
                    "status": "waiting_full_r5_bundle",
                    "expired_slots": expired.get("released_slots", []),
                }
                self._arm_expiry_timer()
                return dict(self.last_result)

            proposal_result = build_automatic_slot_proposals(
                bundle["combined"], now=reference
            )
            if not proposal_result.get("valid"):
                self.last_result = {
                    "status": "source_blocked",
                    "reason": proposal_result.get("reason"),
                    "expired_slots": expired.get("released_slots", []),
                }
                self._arm_expiry_timer()
                return dict(self.last_result)

            # One final revision/ownership check immediately before the writer.
            if (
                self.planner.bundle_snapshot() is not bundle
                or self.planner._generation != bundle.get("planner_published_generation")
                or serial != self._manual_serial
            ):
                self.last_result = {"status": "stale_generation_discarded"}
                self._arm_expiry_timer()
                return dict(self.last_result)

            result = await self.store.async_sync_automatic_plans(
                list(proposal_result["proposals"]), now=reference
            )
            # Store writes may await. Never publish a witness if the planner or
            # manual owner changed while synchronization was in flight.
            if (
                self.planner.bundle_snapshot() is not bundle
                or self.planner._generation != bundle.get("planner_published_generation")
                or serial != self._manual_serial
            ):
                self.last_result = {"status": "stale_generation_after_sync"}
                self._arm_expiry_timer()
                return dict(self.last_result)
            self._manual_pending = False
            self._published_bundle = bundle
            self._published_serial = serial
            self._published_proposals = tuple(deepcopy(proposal_result["proposals"]))
            self.last_result = {
                "status": "ready",
                "source_native_slots": 288,
                "candidate_count": len(proposal_result["proposals"]),
                "rejected": list(proposal_result.get("rejected", [])),
                "expired_slots": expired.get("released_slots", []),
                **result,
                "scheduler_enabled": False,
                "physical_execution_enabled": False,
            }
            self._arm_expiry_timer()
            return dict(self.last_result)
