"""Persistent, non-actuating runtime for DOEMS Step 13 G5 frozen-live parity."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from homeassistant.core import callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .ems_g5_live_parity import compare_frozen_live_snapshot
from .ems_runtime import DOEMSEMSRuntime

_STORE_VERSION = 1
_RUNTIME_ATTR = "_doems_g5_live_parity_runtime"


class DOEMSG5LiveParityRuntime:
    """Capture exactly one current DOEMS EMS state and persist G5 evidence."""

    def __init__(self, ems_runtime: DOEMSEMSRuntime) -> None:
        self.ems_runtime = ems_runtime
        self.hass = ems_runtime.hass
        self.entry = ems_runtime.entry
        self._store: Store[dict[str, Any]] = Store(
            self.hass,
            _STORE_VERSION,
            f"{DOMAIN}.{self.entry.entry_id}.g5_frozen_live_parity",
        )
        self.evidence: dict[str, Any] | None = None
        self.loaded = False
        self.persistence_error: str | None = None
        self._listeners: set[Callable[[], None]] = set()

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)

        def remove() -> None:
            self._listeners.discard(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    async def async_ensure_loaded(self) -> None:
        if self.loaded:
            return
        try:
            raw = await self._store.async_load()
            if isinstance(raw, dict):
                self.evidence = deepcopy(raw)
            self.persistence_error = None
        except Exception as err:  # pragma: no cover - HA storage fault path
            self.evidence = None
            self.persistence_error = f"{type(err).__name__}: {err}"
        self.loaded = True
        self._notify()

    def _frozen_snapshot(self) -> dict[str, Any]:
        """Freeze one internally consistent completed EMS refresh."""
        input_result = self.ems_runtime.input_result
        planner_result = self.ems_runtime.planner_result
        if not isinstance(input_result, dict) or not isinstance(planner_result, dict):
            raise RuntimeError("DOEMS EMS heeft nog geen complete planner-snapshot")
        if self.ems_runtime.soc_percent is None:
            raise RuntimeError("DOEMS EMS heeft geen geldige SOC voor G5")
        if self.ems_runtime.status != "ready":
            raise RuntimeError(
                f"DOEMS EMS is niet ready voor G5: {self.ems_runtime.status}"
            )

        scheduler_slots = deepcopy(
            (self.ems_runtime.scheduler_result or {}).get("scheduler_slots") or {}
        )
        time_contract = deepcopy(input_result.get("time_contract") or {})
        captured_at = (
            self.ems_runtime.last_refresh.isoformat()
            if self.ems_runtime.last_refresh is not None
            else time_contract.get("window_start")
        )

        return {
            "schema_version": 1,
            "captured_at": captured_at,
            "input_result": deepcopy(input_result),
            "time_contract": time_contract,
            "soc_source_entity": self.ems_runtime.soc_entity_id,
            "measured_soc_percent": self.ems_runtime.soc_percent,
            "planner_start_soc_percent": self.ems_runtime.soc_percent,
            "config": deepcopy(self.ems_runtime.settings.as_contract()),
            "profile": getattr(self.ems_runtime.coordinator, "profile", None),
            "scheduler_slots": scheduler_slots,
            "production_summary": {
                "energy_need": deepcopy(planner_result.get("energy_need") or {}),
                "planner_preview": deepcopy(
                    planner_result.get("planner_preview") or {}
                ),
                "plan72": deepcopy(planner_result.get("plan72") or {}),
            },
            "shadow_only": True,
            "service_calls_performed": False,
            "plan_store_mutated_by_capture": False,
            "physical_execution_authority": False,
        }

    async def async_capture_and_compare(self) -> dict[str, Any]:
        """Persist one frozen live G5 A/B comparison."""
        await self.async_ensure_loaded()
        frozen_snapshot = self._frozen_snapshot()
        result = await self.hass.async_add_executor_job(
            compare_frozen_live_snapshot,
            deepcopy(frozen_snapshot),
        )
        self.evidence = {
            "snapshot": frozen_snapshot,
            "result": result,
        }
        try:
            await self._store.async_save(deepcopy(self.evidence))
            self.persistence_error = None
        except Exception as err:  # pragma: no cover - HA storage fault path
            self.persistence_error = f"{type(err).__name__}: {err}"
        self.loaded = True
        self._notify()
        return deepcopy(self.evidence)

    def state(self) -> str:
        if not self.loaded:
            return "initializing"
        if self.evidence is None:
            return "not_captured"
        result = self.evidence.get("result") or {}
        return str(result.get("status") or "blocked")

    def attributes(self) -> dict[str, Any]:
        evidence = self.evidence or {}
        snapshot = evidence.get("snapshot") or {}
        result = evidence.get("result") or {}
        return {
            "gate": "G5",
            "step": "step13_frozen_live_ab",
            "captured": bool(evidence),
            "captured_at": snapshot.get("captured_at"),
            "snapshot_fingerprint": result.get("snapshot_fingerprint"),
            "policy_version": result.get("policy_version"),
            "golden_source": result.get("golden_source"),
            "doems_path": result.get("doems_path"),
            "soc_source_entity": snapshot.get("soc_source_entity"),
            "measured_soc_percent": snapshot.get("measured_soc_percent"),
            "planner_start_soc_percent": snapshot.get(
                "planner_start_soc_percent"
            ),
            "profile": snapshot.get("profile"),
            "window_start": (snapshot.get("time_contract") or {}).get(
                "window_start"
            ),
            "window_end": (snapshot.get("time_contract") or {}).get("window_end"),
            "exact_match": result.get("exact_match"),
            "difference_count": result.get("difference_count"),
            "differences": deepcopy(result.get("differences") or []),
            "blockers": deepcopy(result.get("blockers") or []),
            "golden_decision": deepcopy(result.get("golden_decision")),
            "doems_decision": deepcopy(result.get("doems_decision")),
            "persistence_error": self.persistence_error,
            "shadow_only": True,
            "simulation_mode": True,
            "service_calls_performed": False,
            "plan_store_mutated": False,
            "physical_execution_authority": False,
            "cutover_permitted": False,
        }


def get_g5_live_parity_runtime(
    ems_runtime: DOEMSEMSRuntime,
) -> DOEMSG5LiveParityRuntime:
    runtime = getattr(ems_runtime, _RUNTIME_ATTR, None)
    if isinstance(runtime, DOEMSG5LiveParityRuntime):
        return runtime
    runtime = DOEMSG5LiveParityRuntime(ems_runtime)
    setattr(ems_runtime, _RUNTIME_ATTR, runtime)
    return runtime
