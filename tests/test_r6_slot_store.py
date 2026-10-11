"""R6 actual persistent three-slot store tests with only HA boundary stubbed."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types

from test_r6_slot_bridge_model import NOW, _load_model, _three

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _store_class(monkeypatch):
    _load_model()
    class FakeStore:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.key = key

        async def async_load(self):
            return deepcopy(self.hass.storage.get(self.key))

        async def async_save(self, data):
            self.hass.storage[self.key] = deepcopy(data)
            self.hass.save_count += 1

    def module(name, **attributes):
        result = types.ModuleType(name)
        for k, v in attributes.items():
            setattr(result, k, v)
        monkeypatch.setitem(sys.modules, name, result)
        return result

    module("homeassistant", __path__=[])
    module("homeassistant.core", HomeAssistant=type("HomeAssistant", (), {}))
    module("homeassistant.helpers", __path__=[])
    module("homeassistant.helpers.storage", Store=FakeStore)
    module("homeassistant.util", __path__=[])
    module("homeassistant.util.dt", now=lambda: NOW, DEFAULT_TIME_ZONE=timezone.utc)

    name = "custom_components.doems._r6_store_test"
    spec = importlib.util.spec_from_file_location(name, INTEGRATION / "manual_plan_store.py")
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)
    return instance.DOEMSManualPlanStore


class FakeHass:
    def __init__(self):
        self.storage = {}
        self.save_count = 0


def _candidates():
    model = _load_model()
    return model.build_automatic_slot_proposals(_three(), now=NOW)["proposals"]


def test_r6_three_slots_persist_without_triggering_manual_r5_listeners(monkeypatch):
    StoreClass = _store_class(monkeypatch)

    async def verify():
        hass = FakeHass()
        store = StoreClass(hass, "entry")
        await store.async_load()
        manual_events = []
        all_events = []
        store.add_manual_listener(lambda: manual_events.append("manual"))
        store.add_listener(lambda: all_events.append("entity"))
        candidates = _candidates()
        result = await store.async_sync_automatic_plans(candidates, now=NOW)
        assert result["written_slots"] == [1, 2, 3]
        assert manual_events == []
        assert len(all_events) == 1
        assert hass.save_count == 1
        for slot in (1, 2, 3):
            actual = store.get_plan(slot)
            assert actual["origin"] == "automatic_72h_planner"
            assert actual["lifecycle_status"] == "concept"
            assert actual["planner_identity"] == candidates[slot-1]["planner_identity"]
        unchanged = await store.async_sync_automatic_plans(candidates, now=NOW)
        assert unchanged["changed"] is False
        assert hass.save_count == 1

        restarted = StoreClass(hass, "entry")
        await restarted.async_load()
        for slot in (1, 2, 3):
            assert restarted.get_plan(slot)["origin"] == "automatic_72h_planner"
            assert restarted.get_plan(slot)["planner_identity"] == candidates[slot-1]["planner_identity"]

    asyncio.run(verify())


def test_r6_manual_concept_keeps_priority_even_with_action_geen(monkeypatch):
    StoreClass = _store_class(monkeypatch)

    async def verify():
        store = StoreClass(FakeHass(), "entry")
        await store.async_set_value(2, "power_w", 350)
        manual = store.get_plan(2)
        assert manual["lifecycle_status"] == "concept"
        assert manual["action"] == "geen"
        assert manual["lifecycle_reason"] == "plan_changed"
        result = await store.async_sync_automatic_plans(_candidates(), now=NOW)
        assert 2 not in result["written_slots"]
        assert store.get_plan(2) == manual
        assert sum(store.get_plan(slot)["origin"] == "automatic_72h_planner"
                   for slot in (1, 2, 3)) == 2

    asyncio.run(verify())


def test_r6_direct_manual_edit_claims_automatic_slot(monkeypatch):
    StoreClass = _store_class(monkeypatch)

    async def verify():
        store = StoreClass(FakeHass(), "entry")
        await store.async_sync_automatic_plans(_candidates(), now=NOW)
        await store.async_set_value(1, "target_soc", 73.0)
        claimed = store.get_plan(1)
        assert claimed["origin"] == "manual"
        assert claimed["lifecycle_status"] == "concept"
        assert claimed["planner_identity"] if False else True
        assert "planner_identity" not in claimed
        assert claimed["target_soc"] == 73.0
        await store.async_sync_automatic_plans(_candidates(), now=NOW)
        assert store.get_plan(1) == claimed
        # Other already-matched automatic identities should not be shuffled.
        assert store.get_plan(2)["planner_identity"] == _candidates()[1]["planner_identity"]
        assert store.get_plan(3)["planner_identity"] == _candidates()[2]["planner_identity"]

    asyncio.run(verify())


def test_r6_cancel_and_clear_are_immediately_reusable_no_blacklist(monkeypatch):
    StoreClass = _store_class(monkeypatch)

    async def verify():
        store = StoreClass(FakeHass(), "entry")
        await store.async_sync_automatic_plans(_candidates(), now=NOW)
        await store.async_cancel(1)
        assert store.get_plan(1)["origin"] == "manual"
        assert store.get_plan(1)["lifecycle_status"] == "geannuleerd"
        await store.async_sync_automatic_plans(_candidates(), now=NOW)
        assert store.get_plan(1)["origin"] == "automatic_72h_planner"
        await store.async_clear(1)
        assert store.get_plan(1)["action"] == "geen"
        await store.async_sync_automatic_plans(_candidates(), now=NOW)
        assert store.get_plan(1)["origin"] == "automatic_72h_planner"

    asyncio.run(verify())


def test_r6_replan_preserves_identity_and_stable_slot_without_rewrites(monkeypatch):
    StoreClass = _store_class(monkeypatch)

    async def verify():
        hass = FakeHass()
        store = StoreClass(hass, "entry")
        candidates = _candidates()
        await store.async_sync_automatic_plans(candidates, now=NOW)
        changed = deepcopy(candidates)
        changed[1]["planned_energy_kwh"] += 0.025
        changed[1]["target_soc"] += 0.25
        changed[1]["planner_signature"] += "|revision"
        updated = await store.async_sync_automatic_plans(changed, now=NOW)
        assert updated["written_slots"] == [2]
        assert store.get_plan(2)["planner_identity"] == candidates[1]["planner_identity"]
        assert store.get_plan(2)["planner_signature"] == changed[1]["planner_signature"]
        assert hass.save_count == 2
        again = await store.async_sync_automatic_plans(changed, now=NOW)
        assert again["changed"] is False
        assert hass.save_count == 2

    asyncio.run(verify())


def test_r6_invalid_forecast_cleanup_by_timer_cannot_touch_manual(monkeypatch):
    StoreClass = _store_class(monkeypatch)

    async def verify():
        hass = FakeHass()
        store = StoreClass(hass, "entry")
        proposals = _candidates()
        await store.async_sync_automatic_plans(proposals, now=NOW)
        await store.async_set_value(2, "target_soc", 70.0)
        manual = store.get_plan(2)
        deadline = datetime.fromisoformat(proposals[0]["start_time"]) + timedelta(minutes=10)
        exact = await store.async_release_expired_automatic_plans(now=deadline)
        assert exact["released_slots"] == []
        expired = await store.async_release_expired_automatic_plans(
            now=deadline + timedelta(seconds=1)
        )
        assert expired["released_slots"] == [1]
        assert store.get_plan(2) == manual
        assert store.last_terminal_event(1)["origin"] == "automatic_72h_planner"

    asyncio.run(verify())


def test_r6_legacy_manual_store_load_does_not_claim_auto(monkeypatch):
    StoreClass = _store_class(monkeypatch)

    async def verify():
        hass = FakeHass()
        store = StoreClass(hass, "entry")
        await store.async_set_value(1, "action", "laden")
        persisted = hass.storage[store.storage_key]
        del persisted["plans"]["1"]["origin"]
        hass.storage[store.storage_key] = persisted
        restarted = StoreClass(hass, "entry")
        await restarted.async_load()
        assert restarted.get_plan(1)["origin"] == "manual"
        assert restarted.get_plan(1)["action"] == "laden"

    asyncio.run(verify())


def test_r6_new_runtime_keeps_r5_listener_sources_separate(monkeypatch):
    planner = (INTEGRATION / "automatic_combined_planner.py").read_text(encoding="utf-8")
    projection = (INTEGRATION / "manual_soc_projection.py").read_text(encoding="utf-8")
    lifecycle = (INTEGRATION / "manual_plan_lifecycle.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "automatic_slot_bridge.py").read_text(encoding="utf-8")
    store = (INTEGRATION / "manual_plan_store.py").read_text(encoding="utf-8")
    assert "self.plans.add_manual_listener(" in planner
    assert "self.plans.add_manual_listener(" in projection
    assert "self.store.add_manual_listener(" in lifecycle
    assert "def _notify_automatic" in store
    assert "add_manual_listener" in runtime
    assert "async_track_point_in_utc_time" in runtime
    assert "scheduler_enabled" in runtime
    assert "physical_execution_enabled" in runtime
    assert "async_call(" not in runtime + store
