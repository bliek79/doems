"""R9 Combined to proven Anker adapter interface.

The adapter is injected, never constructed with physical authority here.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from .combined_execution_shadow import evaluate_combined_execution_shadow


class CombinedAnkerBridge:
    def __init__(self, planner: Any, adapter: Any, *, authority: bool = False) -> None:
        self.planner = planner
        self.adapter = adapter
        self.authority = authority
        self._lock = asyncio.Lock()
        self._active: tuple | None = None
        self._reconciliation_required = False

    def _decision(self, now: datetime) -> dict:
        return evaluate_combined_execution_shadow(
            self.planner.snapshot("combined"), now=now
        )

    @staticmethod
    def _identity(decision: dict) -> tuple:
        return (
            decision.get("start"), decision.get("end"),
            decision.get("action"), decision.get("planned_power_w")
        )

    def _still_current(self, identity: tuple) -> bool:
        decision = self._decision(datetime.now(timezone.utc))
        return (
            decision["status"] == "shadow_ready"
            and self._identity(decision) == identity
            and self.authority
            and self.adapter.authority
        )

    async def async_reconcile(self, now: datetime) -> dict:
        """Follow the current Combined quarter, stopping on any change.

        Physical control requires separate explicit authority for both layers.
        """
        async with self._lock:
            decision = self._decision(now)
            identity = self._identity(decision)
            enabled = self.authority and self.adapter.authority
            if not enabled:
                return {**decision, "bridge": "authority_disabled"}
            if self._reconciliation_required:
                await self.adapter.stop()
                self._active = None
                self._reconciliation_required = False
            if decision["status"] != "shadow_ready" or decision["action"] == "idle":
                if self._active is not None:
                    self._reconciliation_required = True
                    await self.adapter.stop()
                    self._active = None
                    self._reconciliation_required = False
                return {**decision, "bridge": "idle_or_blocked"}
            if self._active == identity:
                return {**decision, "bridge": "running"}
            if self._active is not None:
                self._reconciliation_required = True
                await self.adapter.stop()
                self._active = None
                self._reconciliation_required = False
            power = decision["planned_power_w"]
            if not isinstance(power, int) or not 100 <= power <= 3500:
                return {**decision, "bridge": "power_out_of_range"}
            self._reconciliation_required = True
            try:
                acknowledged = await self.adapter.start(
                    action="laden" if decision["action"] == "charge" else "ontladen",
                    power_w=power,
                    revalidate=lambda: self._still_current(identity),
                )
                if acknowledged is not True or not self._still_current(identity):
                    raise RuntimeError("Anker acknowledgement or plan identity failed")
                self._active = identity
                self._reconciliation_required = False
                return {**decision, "bridge": "running"}
            except BaseException:
                await self.adapter.stop()
                self._active = None
                self._reconciliation_required = False
                raise

    async def async_shutdown(self) -> None:
        async with self._lock:
            if self._active is not None or self._reconciliation_required:
                await self.adapter.stop()
                self._active = None
                self._reconciliation_required = False
