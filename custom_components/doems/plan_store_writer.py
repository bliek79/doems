"""Chapter 7 controlled Alpha84-style automatic slot writer.

Only observed validated Bridge candidates are persisted; never handoff to
Scheduler or issue battery commands. Manual and due/active ownership is honored
by the Alpha84 Store and the separate slot assignment.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from homeassistant.util import dt as dt_util

from .plan_slot_assignment import slot_assignment


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
        self._task = None
        self._closed = False
        self.status = "initializing"
        self.last_reason = "startup"

    async def async_setup(self):
        self._unsubscribe = self.bridge.async_add_listener(self.schedule)
        self.schedule()

    def schedule(self):
        if self._closed:
            return
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self._sync())

    async def _sync(self):
        # No physical authority. A failed or calculating generation is not
        # permission to clear valid persisted plans.
        source = self.plan72.snapshot
        bridge = self.bridge.snapshot
        if (source.get("valid") is not True
                or bridge.get("valid") is not True
                or source.get("input_fingerprint") != bridge.get("source_input_fingerprint")
                or source.get("plan_generation") != bridge.get("source_plan_generation")):
            self.status = "blocked"
            self.last_reason = "source_not_ready_or_mismatch"
            return
        assignment = slot_assignment(self.store, bridge, now=dt_util.utcnow())
        if not assignment["valid"]:
            self.status = "blocked"
            self.last_reason = assignment["reason"]
            return
        desired = {}
        try:
            for slot, candidate in assignment["desired"].items():
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
        result = await self.store.async_sync_automatic_plans(desired)
        self.status = "ready"
        self.last_reason = "changed" if result["changed"] else "unchanged"

    async def async_shutdown(self):
        self._closed = True
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
