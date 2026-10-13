"""R7 runtime boundary tests: only software state transitions, never battery calls."""
from __future__ import annotations
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types
from test_r7_scheduler_prestart import NOW, battery, bundle, plan, model

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "doems"


def load_runtime(monkeypatch):
    def mod(name, **values):
        value = types.ModuleType(name)
        value.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, value)
    mod("homeassistant", __path__=[])
    mod("homeassistant.core", HomeAssistant=type("HomeAssistant", (), {}), callback=lambda func: func)
    mod("homeassistant.helpers", __path__=[])
    mod("homeassistant.helpers.event",
        async_track_point_in_utc_time=lambda hass, handler, when: (lambda: None))
    mod("homeassistant.util", __path__=[])
    mod("homeassistant.util.dt", now=lambda: NOW, utcnow=lambda: NOW)
    mod("custom_components", __path__=[])
    mod("custom_components.doems", __path__=[])
    monkeypatch.setitem(sys.modules, "custom_components.doems.r7_model", model)
    spec = importlib.util.spec_from_file_location(
        "custom_components.doems.r7_runtime_test", COMPONENT / "r7_runtime.py")
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)
    return instance.DOEMSR7Scheduler


class FakeHass:
    def __init__(self):
        self.states = {
            f"sensor.{item}": types.SimpleNamespace(last_reported=NOW)
            for item in ("soc", "capacity", "charge_power", "discharge_power", "device_status")
        }
    def async_create_task(self, coro, name=None):
        return asyncio.create_task(coro)


class FakePlanner:
    def __init__(self):
        self._generation = 5
        self.bundle = bundle()
        self.callbacks = []
    def bundle_snapshot(self):
        return self.bundle
    def async_add_listener(self, callback):
        self.callbacks.append(callback)
        return lambda: self.callbacks.remove(callback)


class FakeBattery:
    def __init__(self):
        self.value = battery()
        self.value["source_entities"] = {
            field: f"sensor.{field}"
            for field in ("soc", "capacity", "charge_power", "discharge_power", "device_status")
        }
        self.callbacks = []
    def snapshot(self):
        return dict(self.value)
    def async_add_listener(self, callback):
        self.callbacks.append(callback)
        return lambda: self.callbacks.remove(callback)


class FakeBridge:
    def __init__(self):
        self.last_result = {"status": "ready"}
        self.times_evaluated = 0
    async def async_evaluate(self, *, now):
        self.times_evaluated += 1
        return dict(self.last_result)


class FakeStore:
    def __init__(self):
        self.slots = {
            1: plan(1),
            2: plan(2, origin="manual", lifecycle_status="concept"),
            3: {"action": "geen", "origin": "manual", "lifecycle_status": "concept"},
        }
        self.writes = 0
        self.callbacks = []
    def get_plan(self, slot):
        return deepcopy(self.slots[slot])
    def add_listener(self, callback):
        self.callbacks.append(callback)
        return lambda: self.callbacks.remove(callback)
    async def async_promote_automatic_plan(
        self, slot, *, expected_identity, expected_signature,
        expected_updated_at, gate_approved, now
    ):
        existing = self.slots[slot]
        if not gate_approved or existing.get("origin") != "automatic_72h_planner":
            return False
        if existing.get("lifecycle_status") != "concept":
            return False
        if (existing.get("planner_identity") != expected_identity
            or existing.get("planner_signature") != expected_signature
            or existing.get("lifecycle_updated_at") != expected_updated_at):
            return False
        existing["lifecycle_status"] = "pending"
        self.writes += 1
        for callback in tuple(self.callbacks):
            callback()
        return True


def test_scheduler_promotes_once_without_manual_mutation(monkeypatch):
    Runtime = load_runtime(monkeypatch)
    async def run():
        hass, bridge, store = FakeHass(), FakeBridge(), FakeStore()
        scheduler = Runtime(hass, FakePlanner(), bridge, store, FakeBattery())
        await scheduler.async_setup()
        assert bridge.times_evaluated == 1
        assert store.writes == 1
        assert store.slots[1]["lifecycle_status"] == "pending"
        assert store.slots[1]["origin"] == "automatic_72h_planner"
        assert store.slots[2]["origin"] == "manual"
        assert store.slots[2]["lifecycle_status"] == "concept"
        assert scheduler.last_result["execution_authority"] is False
        await scheduler.async_evaluate(now=NOW)
        assert store.writes == 1
        await scheduler.async_shutdown()
    asyncio.run(run())


def test_missing_fresh_soc_prevents_promotion(monkeypatch):
    Runtime = load_runtime(monkeypatch)
    async def run():
        hass, bridge, store = FakeHass(), FakeBridge(), FakeStore()
        hass.states["sensor.soc"].last_reported = datetime(2026, 10, 13, 7, tzinfo=timezone.utc)
        scheduler = Runtime(hass, FakePlanner(), bridge, store, FakeBattery())
        await scheduler.async_setup()
        assert store.writes == 0
        assert "battery_sources_stale" in scheduler.last_result["safety_blockers"]
        await scheduler.async_shutdown()
    asyncio.run(run())
