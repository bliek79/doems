"""Lightweight Scheduler runtime. Never requests a Plan72 recalculation."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import CONF_PLAN72_MAX_CHARGE_POWER_W, CONF_PLAN72_MAX_DISCHARGE_POWER_W
from .scheduler import AUTOMATIC, evaluate, timestamp


class SchedulerRuntime:
    def __init__(self, hass, entry, store, plan72, bridge):
        self.hass, self.entry, self.store = hass, entry, store
        self.plan72, self.bridge = plan72, bridge
        self.listeners = []
        self._unsubs = []
        self._boundary_unsub = None
        self._pending = None
        self._closed = False
        self.snapshot = {}

    async def async_setup(self):
        self._unsubs.append(self.store.add_listener(self.schedule))
        for source in (self.plan72, self.bridge):
            if source is not None:
                self._unsubs.append(source.async_add_listener(self.schedule))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(seconds=10)))
        self.refresh()

    def async_add_listener(self, listener):
        self.listeners.append(listener)
        def remove():
            if listener in self.listeners:
                self.listeners.remove(listener)
        return remove

    @callback
    def schedule(self):
        if not self._closed and self._pending is None:
            # Store callbacks can run during its durable transaction. Read only
            # after that turn commits/rolls back and the visible snapshot settles.
            self._pending = asyncio.get_running_loop().call_soon(self.refresh)

    @callback
    def _tick(self, _scheduled_time):
        # The actual clock is authoritative, never the intended callback time.
        self.refresh()

    @callback
    def refresh(self):
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        if self._closed:
            return
        now = dt_util.utcnow()
        revision = self.store.revision
        plans = {slot: self.store.get_plan(slot) for slot in range(1, 4)}
        source = self.plan72.snapshot if self.plan72 is not None else {}
        bridge = self.bridge.snapshot if self.bridge is not None else {}
        blocker = None
        if self.plan72 is None or self.bridge is None:
            blocker = "planning_not_enabled"
        elif source.get("valid") is not True or bridge.get("valid") is not True:
            blocker = "source_not_ready"
        elif (not source.get("input_fingerprint") or source.get("plan_generation") is None
              or source.get("input_fingerprint") != bridge.get("source_input_fingerprint")
              or source.get("plan_generation") != bridge.get("source_plan_generation")):
            blocker = "source_generation_or_fingerprint_mismatch"
        options = self.entry.options
        result = evaluate(plans, now=now, storage_revision=revision, source_blocker=None,
                          max_charge_power_w=options.get(CONF_PLAN72_MAX_CHARGE_POWER_W),
                          max_discharge_power_w=options.get(CONF_PLAN72_MAX_DISCHARGE_POWER_W))
        result.update(source_plan_generation=source.get("plan_generation"),
                      source_input_fingerprint=source.get("input_fingerprint"),
                      source_status=source.get("status"), source_consistent=blocker is None,
                      source_blocker=blocker, prestart_revalidation_required=True)
        for slot, detail in result["scheduler_slots"].items():
            if detail.get("origin") != AUTOMATIC:
                continue
            identity = detail.get("planner_identity")
            current = next((p for p in bridge.get("eligible_candidates", [])
                            if p.get("planner_identity") == identity), None)
            # Diagnostic only: a protected due/active plan is not rewritten or
            # rejected just because a rolling forecast has another generation.
            detail["source_generation_matches"] = detail.get("source_plan_generation") == source.get("plan_generation")
            detail["source_fingerprint_matches"] = detail.get("source_input_fingerprint") == source.get("input_fingerprint")
            detail["current_identity_present"] = current is not None
            detail["current_signature_matches"] = (current.get("planner_signature") == detail.get("planner_signature")) if current else None
            detail["prestart_revalidation_required"] = True
        if (revision != self.store.revision
                or any(plans[i] != self.store.get_plan(i) for i in range(1, 4))
                or self.plan72 is not None and self.plan72.snapshot is not source
                or self.bridge is not None and self.bridge.snapshot is not bridge):
            # Publish no obsolete selection, and read the new snapshot next turn.
            result = evaluate(plans, now=now, storage_revision=revision,
                              max_charge_power_w=options.get(CONF_PLAN72_MAX_CHARGE_POWER_W),
                              max_discharge_power_w=options.get(CONF_PLAN72_MAX_DISCHARGE_POWER_W),
                              source_blocker="superseded_snapshot")
            self.schedule()
        self.snapshot = deepcopy(result)
        if self._boundary_unsub is not None:
            self._boundary_unsub()
            self._boundary_unsub = None
        boundary = timestamp(result.get("next_evaluation_at"))
        if boundary is not None:
            self._boundary_unsub = async_track_point_in_utc_time(self.hass, self._tick, boundary)
        for listener in tuple(self.listeners):
            listener()

    async def async_shutdown(self):
        self._closed = True
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        if self._boundary_unsub is not None:
            self._boundary_unsub()
            self._boundary_unsub = None
        for remove in self._unsubs:
            remove()
        self._unsubs.clear()
        self.listeners.clear()
