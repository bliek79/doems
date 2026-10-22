"""R9 Combined execution handoff to the proven R8 controller.

No physical authority is granted by this module.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from .combined_execution_shadow import evaluate_combined_execution_shadow
from .execution_controller import ExecutionController


class CombinedAnkerBridge:
    def __init__(self, planner: Any, adapter: Any, *, battery: Any = None,
                 authority: bool = False, exclusive: bool = False) -> None:
        self.planner = planner
        self.adapter = adapter
        self.battery = battery
        self.authority = authority
        self.exclusive = exclusive
        self._lock = asyncio.Lock()
        self.controller = ExecutionController(
            adapter, authorized=self._authorized, revalidate=self._still_current
        )

    def _authorized(self) -> bool:
        return bool(self.authority and self.exclusive and self.adapter.authority)

    def _decision(self, now: datetime) -> dict:
        return evaluate_combined_execution_shadow(
            self.planner.snapshot("combined"), now=now
        )

    @staticmethod
    def _identity(decision: dict) -> tuple:
        return (decision.get("start"), decision.get("end"),
                decision.get("action"), decision.get("planned_power_w"))

    def _still_current(self, identity: tuple) -> bool:
        decision = self._decision(datetime.now(timezone.utc))
        return (self._authorized() and decision["status"] == "shadow_ready"
                and self._identity(decision) == identity)

    def _soc(self) -> float | None:
        if self.battery is None:
            return None
        snapshot = self.battery.snapshot()
        if snapshot.get("status") != "ready":
            return None
        try:
            value = float(snapshot["sources"]["soc"]["state"])
        except (KeyError, TypeError, ValueError):
            return None
        return value if isfinite(value) and 0 <= value <= 100 else None

    async def async_reconcile(self, now: datetime) -> dict:
        async with self._lock:
            decision = self._decision(now)
            if not self._authorized():
                return {**decision, "bridge": "authority_disabled"}
            identity = self._identity(decision)
            session = self.controller.session
            if session is not None:
                soc = self._soc()
                await self.controller.monitor(
                    now=now, soc_percent=soc, sources_fresh=soc is not None,
                    controller_exclusive=self.exclusive,
                    command_acknowledged=(
                        self.adapter._power_matches(session["power_w"])
                        and self.adapter._state("operating_mode") == "third_party_control"
                    ),
                    plan_identity_matches=(
                        decision["status"] == "shadow_ready"
                        and identity == session["identity"]
                    ),
                    safety_clear=decision["status"] == "shadow_ready",
                )
            elif self.controller.reconciliation_required:
                await self.controller.stop()
            if decision["status"] != "shadow_ready" or decision["action"] == "idle":
                return {**decision, "bridge": "idle_or_blocked"}
            if self.controller.session is not None:
                return {**decision, "bridge": "running"}
            power = decision["planned_power_w"]
            if type(power) is not int or not 100 <= power <= 3500:
                return {**decision, "bridge": "power_out_of_range"}
            soc = self._soc()
            if soc is None:
                return {**decision, "bridge": "soc_unavailable"}
            snapshot = self.planner.snapshot("combined")
            slot = next((s for s in snapshot.get("native_slots", [])
                         if s.get("start") == decision["start"]), None)
            if slot is None:
                return {**decision, "bridge": "slot_missing"}
            floor = float(slot.get("automatic_floor_soc_percent", 100))
            if decision["action"] == "discharge" and soc <= floor:
                return {**decision, "bridge": "reserve_floor"}
            target = 100.0 if decision["action"] == "charge" else floor
            if decision["action"] == "charge" and soc >= target:
                return {**decision, "bridge": "target_reached"}
            await self.controller.start(
                identity=identity,
                action="laden" if decision["action"] == "charge" else "ontladen",
                power_w=power, target_soc=target, max_runtime_h=0.25, now=now,
            )
            return {**decision, "bridge": "running"}

    async def async_shutdown(self) -> None:
        async with self._lock:
            if self.controller.session is not None or self.controller.reconciliation_required:
                await self.controller.stop()
