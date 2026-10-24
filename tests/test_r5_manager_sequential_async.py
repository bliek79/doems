"""Exercise real R5 manager scheduling without Home Assistant installation.

The CI repository has no HA package. Stub only HA's import boundary; execute
the actual manager coroutine/worker state machine with a real asyncio executor.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import threading
import types

from test_alpha7_1_planner_migration_contract import _load


def _load_manager(monkeypatch, compute):
    _load("automatic_combined_planner_model")  # Ensure package namespace.
    def module(name, **attrs):
        value = types.ModuleType(name)
        for key, item in attrs.items():
            setattr(value, key, item)
        monkeypatch.setitem(sys.modules, name, value)
        return value

    module("homeassistant", __path__=[])
    module("homeassistant.config_entries", ConfigEntry=type("ConfigEntry", (), {}))
    module("homeassistant.core",
           HomeAssistant=type("HomeAssistant", (), {}),
           callback=lambda func: func)
    module("homeassistant.util", __path__=[])
    module("homeassistant.util.dt",
           utcnow=lambda: datetime.now(timezone.utc),
           DEFAULT_TIME_ZONE=timezone.utc)
    classes = {
        "battery_contract": ("DOEMSBatteryInputContract",),
        "energy_coordinator": ("DOEMSEnergyCoordinator",),
        "manual_plan_model": ("PLAN_SLOT_COUNT",),
        "manual_plan_store": ("DOEMSManualPlanStore",),
        "prices": ("DOEMSPricesManager",),
        "solar_forecast": ("SolarForecastManager",),
    }
    for path, attrs in classes.items():
        values = {key: (3 if key == "PLAN_SLOT_COUNT" else type(key, (), {}))
                  for key in attrs}
        module("custom_components.doems." + path, **values)
    class Cancelled(RuntimeError):
        pass
    class Budget(RuntimeError):
        pass
    module("custom_components.doems.automatic_combined_planner_model",
           PlannerComputeCancelled=Cancelled,
           PlannerComputeBudgetExceeded=Budget)
    module("custom_components.doems.automatic_combined_planner_runtime",
           RUNTIME_VERSION="sequential_test_runtime",
           PLANNER_COMPUTE_BUDGET_SECONDS=20.0,
           make_planner_work_guard=lambda stop: lambda: None,
           compute_planner_bundle=compute,
           planner_cycle_id=lambda reference: "2026-10-08T18:00:00+00:00",
           planner_request_signature=lambda **kwargs: "test-signature")
    path = (Path(__file__).resolve().parents[1] /
            "custom_components/doems/automatic_combined_planner.py")
    name = "custom_components.doems._r5_manager_test_instance"
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj.DOEMSPlannerManager


class FakePlans:
    def __init__(self):
        self.values = {
            i: {"lifecycle_status": "draft", "action": "geen"}
            for i in (1, 2, 3)
        }

    def get_plan(self, slot):
        return dict(self.values[slot])


class FakeHass:
    def async_create_task(self, coroutine, name=None):
        return asyncio.create_task(coroutine, name=name)

    async def async_add_executor_job(self, compute):
        return await asyncio.to_thread(compute)


async def _until_idle(manager):
    for _ in range(500):
        if manager._planner_task is None and manager._pending_request is None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("sequential worker failed to finish")


def _make_instance(cls):
    manager = cls(
        hass=FakeHass(), entry=types.SimpleNamespace(options={}),
        energy=None, solar=None, prices=None, battery=None,
        plans=FakePlans(),
    )
    def freeze(reason):
        return ({
            "reason": reason,
            "cycle_id": "2026-10-08T18:00:00+00:00",
            "request_signature": "test-signature",
            "compute_kwargs": {
                "reference": datetime.now(timezone.utc),
                "energy_records": [], "energy_profile": "normal",
                "local_timezone": timezone.utc,
                "solar_slots": [], "plans": [],
                "start_soc_percent": 50.0, "capacity_kwh": 7.1,
                "price_by_start": {}, "settings": {},
            },
        }, [])
    manager._freeze_request = freeze
    return manager


def _fake_compute(calls, gate=None):
    def compute(**kwargs):
        stage = kwargs["stage"]
        calls.append((stage, [dict(x) for x in kwargs["plans"]]))
        if gate is not None and stage == "automatic":
            assert gate.wait(timeout=3), "automatic gate never released"
        if stage == "automatic":
            assert kwargs["plans"] == []
            return {
                "automatic": {
                    "status": "ready", "valid": True,
                    "native_slot_count": 288,
                    "native_slots": [{"index": i} for i in range(288)],
                    "mode": "automatic_planner",
                },
                "_prepared_energy_slots": [{"index": i} for i in range(288)],
                "planner_input_signature": "automatic-input",
            }
        assert stage == "combined"
        assert kwargs["automatic_snapshot"]["native_slot_count"] == 288
        assert len(kwargs["prebuilt_energy_slots"]) == 288
        active = [
            x["slot"] for x in kwargs["plans"]
            if x.get("lifecycle_status") == "pending"
        ]
        return {
            "combined": {
                "status": "ready", "valid": True,
                "native_slot_count": 288,
                "native_slots": [{"index": i} for i in range(288)],
                "manual_commitment_count": len(active),
                "manual_commitment_slots": active,
                "mode": "combined_planner",
            },
            "planner_input_signature": "combined-input",
        }
    return compute


def test_manual_event_recomputes_only_combined_after_quarter(monkeypatch):
    calls = []
    Manager = _load_manager(monkeypatch, _fake_compute(calls))

    async def check():
        manager = _make_instance(Manager)
        await manager.async_request_refresh("energy_quarter_or_profile")
        await _until_idle(manager)
        assert [name for name, _ in calls] == ["automatic", "combined"]
        assert manager.snapshot("combined")["native_slot_count"] == 288
        manager.plans.values[1] = {
            "lifecycle_status": "pending", "action": "laden"
        }
        await manager.async_request_manual_refresh()
        await _until_idle(manager)
        assert [name for name, _ in calls] == [
            "automatic", "combined", "combined"
        ]
        assert manager._automatic_compute_count == 1
        assert manager._combined_compute_count == 2
        assert manager.snapshot("combined")["manual_commitment_slots"] == [1]
        assert manager.bundle_snapshot()["valid"] is True

    asyncio.run(check())


def test_manual_edit_during_automatic_does_not_cancel_automatic(monkeypatch):
    calls = []
    gate = threading.Event()
    Manager = _load_manager(monkeypatch, _fake_compute(calls, gate))

    async def check():
        manager = _make_instance(Manager)
        await manager.async_request_refresh("energy_quarter_or_profile")
        for _ in range(100):
            if calls:
                break
            await asyncio.sleep(0.01)
        assert calls and calls[0][0] == "automatic"
        manager.plans.values[2] = {
            "lifecycle_status": "pending", "action": "ontladen"
        }
        await manager.async_request_manual_refresh()
        assert manager._automatic_compute_count == 1
        gate.set()
        await _until_idle(manager)
        assert [name for name, _ in calls] == ["automatic", "combined"]
        assert manager.snapshot("combined")["manual_commitment_slots"] == [2]
        assert manager._cancel_count == 0
        assert manager._automatic_published_generation > 0

    try:
        asyncio.run(check())
    finally:
        gate.set()
