"""P3 Alpha84 integration: real plan-store reconciliation into third persistent slot.

Runs the actual DOEMSManualPlanStore logic with stubbed HA persistence,
without physical battery services or execution authority.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"
BASE = datetime(2026, 10, 28, 0, 0, tzinfo=timezone.utc)
NOW = BASE - timedelta(hours=1)


@pytest.fixture
def components(monkeypatch):
    for name, path in (
        ("custom_components", ROOT / "custom_components"),
        ("custom_components.doems", INTEGRATION),
    ):
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = [str(path)]
            monkeypatch.setitem(sys.modules, name, package)

    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    storage = types.ModuleType("homeassistant.helpers.storage")
    util = types.ModuleType("homeassistant.util")
    util.__path__ = []
    dt = types.ModuleType("homeassistant.util.dt")
    dt.now = lambda: NOW
    dt.DEFAULT_TIME_ZONE = timezone.utc

    class MemoryStore:
        def __init__(self, *args, **kwargs):
            self.value = None
        async def async_load(self):
            return self.value
        async def async_save(self, value):
            self.value = value

    storage.Store = MemoryStore
    helpers.storage = storage
    util.dt = dt
    ha.core = core
    ha.helpers = helpers
    ha.util = util
    for name, module in (
        ("homeassistant", ha), ("homeassistant.core", core),
        ("homeassistant.helpers", helpers),
        ("homeassistant.helpers.storage", storage),
        ("homeassistant.util", util), ("homeassistant.util.dt", dt),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    model = importlib.import_module("custom_components.doems.automatic_slot_bridge_model")
    store_module = importlib.import_module("custom_components.doems.manual_plan_store")
    return model, store_module


def combined():
    rows = []
    for i in range(288):
        start = BASE + timedelta(minutes=15 * i)
        kwh = 0.6 if 0 <= i < 4 else (0.15 if 8 <= i < 12 or 16 <= i < 20 else 0)
        rows.append({
            "index": i, "start": start.isoformat(),
            "end": (start + timedelta(minutes=15)).isoformat(),
            "start_soc_percent": 20, "charge_from_grid_safety_kwh": kwh,
            "charge_from_grid_trade_kwh": 0, "trade_discharge_to_grid_kwh": 0,
            "manual_slots": [], "manual_overlap_seconds": 0,
        })
    return {
        "status": "ready", "valid": True, "native_slot_count": 288,
        "native_slots": rows, "capacity_kwh": 7.1,
        "charge_efficiency_percent": 92, "discharge_efficiency_percent": 92,
        "max_charge_power_w": 2400, "max_discharge_power_w": 3500,
    }


@pytest.mark.asyncio
async def test_alpha84_active_first_pending_second_free_third_gets_later_valid_proposal(components):
    model, mod = components
    proposals = model.build_automatic_slot_proposals(combined(), now=NOW)["proposals"]
    assert len(proposals) == 3
    assert proposals[0]["energy_shortfall_kwh"] == 0.08
    store = mod.DOEMSManualPlanStore(object(), "p3_test")
    initial = await store.async_sync_automatic_plans(proposals[:2], now=NOW)
    assert initial["written_slots"] == [1, 2]

    # Simulate one running, one pending, one free (the Alpha84 regression).
    store._plans[1]["lifecycle_status"] = "actief"
    store._plans[2]["lifecycle_status"] = "pending"
    later = await store.async_sync_automatic_plans(proposals, now=BASE + timedelta(minutes=1))
    assert later["written_slots"] == [3]
    third = store.get_plan(3)
    assert third["planner_identity"] == proposals[2]["planner_identity"]
    assert third["origin"] == mod.AUTO_ORIGIN
    assert store.get_plan(1)["lifecycle_status"] == "actief"
    assert store.get_plan(2)["lifecycle_status"] == "pending"
    assert third["requested_energy_kwh"] == 0.6
    assert third["energy_shortfall_kwh"] == 0
    assert store._store.value["plans"]["3"]["planner_identity"] == proposals[2]["planner_identity"]


@pytest.mark.asyncio
async def test_alpha84_manual_third_slot_is_not_overwritten(components):
    model, mod = components
    proposals = model.build_automatic_slot_proposals(combined(), now=NOW)["proposals"]
    store = mod.DOEMSManualPlanStore(object(), "p3_manual")
    await store.async_sync_automatic_plans(proposals[:2], now=NOW)
    store._plans[1]["lifecycle_status"] = "actief"
    store._plans[2]["lifecycle_status"] = "pending"
    store._plans[3]["action"] = "laden"
    store._plans[3]["origin"] = "manual"
    store._plans[3]["lifecycle_status"] = "pending"
    result = await store.async_sync_automatic_plans(proposals, now=BASE + timedelta(minutes=1))
    assert result["written_slots"] == []
    assert store.get_plan(3)["origin"] == "manual"
