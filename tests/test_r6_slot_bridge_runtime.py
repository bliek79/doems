"""R6 integration boundary: only complete, current R5 bundles may fill slots."""
from __future__ import annotations

import asyncio
from datetime import timezone
import importlib.util
from pathlib import Path
import sys
import types

from test_r6_slot_bridge_model import NOW, _combined, _load_model, _three

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_r6_runtime_never_writes_from_unfinished_or_pre_manual_combined(monkeypatch):
    _load_model()

    def module(name, **values):
        result = types.ModuleType(name)
        for k, v in values.items():
            setattr(result, k, v)
        monkeypatch.setitem(sys.modules, name, result)
        return result

    class FakeHass:
        def async_create_task(self, coro, name=None):
            return asyncio.create_task(coro, name=name)

    class FakePlanner:
        def __init__(self):
            self._generation = 3
            self._manual_revision = 0
            self.bundle = {
                "status": "ready", "valid": True,
                "automatic": {"valid": True, "native_slot_count": 288},
                "combined": _three(),
                "planner_published_generation": 3,
                "planner_manual_revision": 0,
            }
            self.listeners = []

        def bundle_snapshot(self):
            return self.bundle

        def async_add_listener(self, callback):
            self.listeners.append(callback)
            return lambda: self.listeners.remove(callback)

    class FakeStore:
        def __init__(self):
            self.plans = {i: {"origin": "manual", "lifecycle_status": "concept"} for i in (1, 2, 3)}
            self.manual_listeners = []
            self.write_calls = []

        def get_plan(self, slot):
            return self.plans[slot]

        def add_manual_listener(self, cb):
            self.manual_listeners.append(cb)
            return lambda: self.manual_listeners.remove(cb)

        async def async_release_expired_automatic_plans(self, *, now):
            return {"changed": False, "released_slots": []}

        async def async_sync_automatic_plans(self, proposals, *, now):
            self.write_calls.append(proposals)
            return {"changed": True, "written_slots": [1, 2, 3]}

    module("homeassistant", __path__=[])
    module("homeassistant.core", HomeAssistant=FakeHass, callback=lambda x: x)
    module("homeassistant.helpers", __path__=[])
    module("homeassistant.helpers.event",
           async_track_point_in_utc_time=lambda hass, callback, when: (lambda: None))
    module("homeassistant.util", __path__=[])
    module("homeassistant.util.dt", now=lambda: NOW, utcnow=lambda: NOW)
    module("custom_components.doems.automatic_combined_planner",
           DOEMSPlannerManager=FakePlanner)
    module("custom_components.doems.manual_plan_store",
           DOEMSManualPlanStore=FakeStore,
           AUTO_ORIGIN="automatic_72h_planner",
           _automatic_expiry=lambda plan: None)

    spec = importlib.util.spec_from_file_location(
        "custom_components.doems._r6_runtime_test",
        INTEGRATION / "automatic_slot_bridge.py"
    )
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)

    async def check():
        planner = FakePlanner()
        store = FakeStore()
        bridge = instance.DOEMSAutoSlotBridge(FakeHass(), planner, store)
        await bridge.async_setup()
        assert len(store.write_calls) == 1
        assert len(store.write_calls[0]) == 3

        planner._generation += 1  # Automatic stage just started, Combined stale
        await bridge.async_evaluate(now=NOW)
        assert len(store.write_calls) == 1
        planner._generation -= 1

        # Manual edited an auto slot: R5 has not yet recomputed Combined.
        for listener in store.manual_listeners:
            listener()
        await bridge.async_evaluate(now=NOW)
        assert len(store.write_calls) == 1
        assert bridge.last_result["status"] == "waiting_full_r5_bundle"

        # The complete new Combined publication now owns the Manual revision.
        planner._manual_revision = 1
        planner._generation = 4
        planner.bundle = {
            "status": "ready", "valid": True,
            "automatic": {"valid": True, "native_slot_count": 288},
            "combined": _three(),
            "planner_published_generation": 4,
            "planner_manual_revision": 1,
        }
        await bridge.async_evaluate(now=NOW)
        assert len(store.write_calls) == 2
        assert bridge.last_result["scheduler_enabled"] is False
        assert bridge.last_result["physical_execution_enabled"] is False

        # Provider failure must never write an automatic proposal.
        planner.bundle = {
            "status": "blocked", "valid": False, "automatic": {}, "combined": {}
        }
        await bridge.async_evaluate(now=NOW)
        assert len(store.write_calls) == 2
        await bridge.async_shutdown()

    asyncio.run(check())
