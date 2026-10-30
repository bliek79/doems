"""Chapter 7 controlled Alpha84-style automatic slot writer.

Only observed validated Bridge candidates are persisted and marked pending.
No Scheduler is installed and no battery commands are issued. Manual and due/active ownership is honored
by the Alpha84 Store and the separate slot assignment.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .plan_slot_assignment import slot_assignment
from .energy_forecast import ceil_quarter


def bridge_plan(candidate):
    """Translate native quarter action without losing the hard end or SOC provenance."""
    action = candidate.get("action")
    if action not in {"charge", "discharge"}:
        raise ValueError("invalid_bridge_action")
    for field in ("planner_identity", "planner_signature", "start_time",
                  "power_start_time", "planned_end_time", "power_w",
                  "target_soc", "command_target_soc", "projected_end_soc",
                  "planned_energy_kwh", "max_runtime_h"):
        if candidate.get(field) is None:
            raise ValueError("missing_bridge_" + field)
    return {
        "action": "laden" if action == "charge" else "ontladen",
        "execution_mode": "gepland",
        "start_time": candidate["start_time"],
        "power_start_time": candidate["power_start_time"],
        "planned_end_time": candidate["planned_end_time"],
        "power_w": candidate["power_w"],
        "target_soc": candidate["target_soc"],
        "command_target_soc": candidate["command_target_soc"],
        "projected_end_soc": candidate["projected_end_soc"],
        "max_runtime_h": candidate["max_runtime_h"],
        "max_start_delay_min": 0,
        "purpose": candidate.get("purpose"),
        "planner_identity": candidate["planner_identity"],
        "planner_signature": candidate["planner_signature"],
        "planned_energy_kwh": candidate["planned_energy_kwh"],
        "requested_energy_kwh": candidate.get("requested_energy_kwh"),
        "energy_shortfall_kwh": candidate.get("energy_shortfall_kwh"),
        "source_plan_generation": candidate.get("source_plan_generation"),
        "source_input_fingerprint": candidate.get("source_input_fingerprint"),
        "source_window_id": candidate.get("source_window_id"),
    }


class PlanStoreWriter:
    def __init__(self, hass, store, plan72, bridge):
        self.hass, self.store, self.plan72, self.bridge = hass, store, plan72, bridge
        self._unsubscribe = None
        self._store_unsubscribe = None
        self._timer_unsubscribe = None
        self._task = None
        self._closed = False
        self._dirty = False
        self.diagnostics = {}
        self.status = "initializing"
        self.last_reason = "startup"

    async def async_setup(self):
        self._unsubscribe = self.bridge.async_add_listener(self.schedule)
        self._store_unsubscribe = self.store.add_listener(self.schedule)
        self._timer_unsubscribe = async_track_time_interval(
            self.hass, lambda now: self.schedule(), timedelta(seconds=30))
        self.schedule()

    def schedule(self):
        if self._closed:
            return
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self._drain())

    async def _drain(self):
        while self._dirty and not self._closed:
            self._dirty = False
            try:
                await self._sync()
            except (ValueError, OSError) as error:
                self.status = "blocked"
                self.last_reason = str(error)

    async def _sync(self):
        await self.store.async_release_expired_automatic_plans()
        await self.store.async_expire_manual_plans()
        # No physical authority. A failed or calculating generation is not
        # permission to clear valid persisted plans.
        source = self.plan72.snapshot
        bridge = self.bridge.snapshot
        try:
            source_start = datetime.fromisoformat(str(source.get("start")).replace("Z", "+00:00"))
            current_window = (source_start.tzinfo is not None
                              and source_start.astimezone(timezone.utc) == ceil_quarter(dt_util.utcnow()))
        except (ValueError, TypeError):
            current_window = False
        if (not current_window or source.get("valid") is not True
                or bridge.get("valid") is not True
                or source.get("input_fingerprint") != bridge.get("source_input_fingerprint")
                or source.get("plan_generation") != bridge.get("source_plan_generation")):
            self.status = "blocked"
            self.last_reason = "source_not_ready_or_mismatch"
            return
        revision = self.store.revision
        assignment = slot_assignment(self.store, bridge, now=dt_util.utcnow())
        if not assignment["valid"]:
            self.status = "blocked"
            self.last_reason = assignment["reason"]
            return
        self.diagnostics = {"generation": assignment["source_plan_generation"],
                            "fingerprint": assignment["source_input_fingerprint"],
                            "overflow": sum(item["reason"] == "no_free_slot" for item in assignment["unassigned"])}
        desired = {}
        try:
            for slot, candidate in assignment["desired"].items():
                if (candidate.get("source_plan_generation") != source.get("plan_generation")
                        or candidate.get("source_input_fingerprint") != source.get("input_fingerprint")):
                    raise ValueError("candidate_source_mismatch")
                desired[slot] = bridge_plan(candidate)
        except (ValueError, TypeError, KeyError) as err:
            self.status = "blocked"
            self.last_reason = str(err)
            return
        # No awaits between latest-snapshot check and store writer call: the
        # source generation and candidate mapping belong to one event-loop turn.
        if (self.plan72.snapshot is not source
                or self.bridge.snapshot is not bridge
                or self._closed):
            self.status = "blocked"
            self.last_reason = "superseded_source"
            return
        result = await self.store.async_sync_automatic_plans(
            desired, expected_revision=revision,
            source_is_current=lambda: (self.plan72.snapshot is source
                                      and self.bridge.snapshot is bridge and not self._closed
                                      and ceil_quarter(dt_util.utcnow()) == source_start),
        )
        await self.store.async_handoff_automatic_plans(
            {slot: plan["planner_signature"] for slot, plan in desired.items()},
            source_is_current=lambda: (self.plan72.snapshot is source
                                      and self.bridge.snapshot is bridge and not self._closed
                                      and ceil_quarter(dt_util.utcnow()) == source_start),
        )
        self.status = "ready"
        self.last_reason = "changed" if result["changed"] else "unchanged"

    async def async_shutdown(self):
        self._closed = True
        for unsubscribe in (self._store_unsubscribe, self._timer_unsubscribe):
            if unsubscribe is not None:
                unsubscribe()
        self._store_unsubscribe = self._timer_unsubscribe = None
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
