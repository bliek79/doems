"""Integration regressions: real R6 quarter -> Plan Store -> R7 -> R6 expiry."""
from __future__ import annotations
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import pytest
from test_r6_slot_bridge_model import NOW, _load_model, _rows, _combined
from test_r6_slot_store import _store_class, FakeHass
from test_r7_scheduler_prestart import model as r7, battery, bundle


def _quarter_proposal():
    rows = _rows()
    rows[0]["charge_from_grid_safety_kwh"] = 0.05
    plans = _load_model().build_automatic_slot_proposals(_combined(rows), now=NOW)
    assert plans["valid"]
    assert len(plans["proposals"]) == 1
    proposal = plans["proposals"][0]
    assert proposal["max_runtime_h"] == 0.25
    assert proposal["purpose"] == "veiligheidsladen"
    return proposal


def test_r6_quarter_enters_r7_and_r6_expiry_without_manual_rule_change(monkeypatch):
    Store = _store_class(monkeypatch)
    async def run():
        hass = FakeHass()
        store = Store(hass, "quarter")
        quarter = _quarter_proposal()
        await store.async_sync_automatic_plans([quarter], now=NOW)
        initial = store.get_plan(1)
        assert initial["origin"] == "automatic_72h_planner"
        assert store.plan_status(1) == "concept"
        assert store.schedule_blockers(1) == []
        start = datetime.fromisoformat(initial["start_time"])
        decision = r7.evaluate_r7(
            now=start, plans={i: store.get_plan(i) for i in (1, 2, 3)},
            bundle=bundle(), battery=battery(), bridge_ready=True,
            planner_generation=5, source_fresh=True,
        )
        assert decision["selected_slot"] == 1
        assert decision["can_promote"]
        assert decision["safety_blockers"] == []
        assert decision["prestart_blockers"] == []
        manual_events = []
        store.add_manual_listener(lambda: manual_events.append(True))
        assert await store.async_promote_automatic_plan(
            1, expected_identity=initial["planner_identity"],
            expected_signature=initial["planner_signature"],
            expected_updated_at=initial["lifecycle_updated_at"],
            gate_approved=True, now=start,
        )
        promoted = store.get_plan(1)
        assert promoted["lifecycle_status"] == "pending"
        assert promoted["origin"] == "automatic_72h_planner"
        assert promoted["planner_identity"] == initial["planner_identity"]
        assert store.plan_status(1) == "gepland"
        assert store.schedule_blockers(1) == []
        assert not manual_events
        restarted = Store(hass, "quarter")
        await restarted.async_load()
        assert restarted.get_plan(1)["lifecycle_status"] == "pending"
        deadline = start + timedelta(minutes=10)
        assert not (await restarted.async_release_expired_automatic_plans(now=deadline))["changed"]
        freed = await restarted.async_release_expired_automatic_plans(
            now=deadline + timedelta(seconds=1)
        )
        assert freed["released_slots"] == [1]
        assert restarted.last_terminal_event(1)["planner_identity"] == initial["planner_identity"]
    asyncio.run(run())


def test_manual_025_still_rejected_and_manual_05_preserved(monkeypatch):
    Store = _store_class(monkeypatch)
    async def run():
        store = Store(FakeHass(), "manual-protect")
        await store.async_set_value(2, "action", "laden")
        await store.async_set_value(2, "start_time", (NOW+timedelta(hours=3)).isoformat())
        await store.async_set_value(2, "max_runtime_h", 0.25)
        assert "max_runtime_out_of_range" in store.schedule_blockers(2)
        with pytest.raises(ValueError, match="max_runtime_out_of_range"):
            await store.async_schedule(2)
        await store.async_set_value(2, "max_runtime_h", 0.5)
        assert store.schedule_blockers(2) == []
        await store.async_schedule(2)
        manual = store.get_plan(2)
        assert manual["origin"] == "manual"
        assert manual["lifecycle_status"] == "pending"
        await store.async_sync_automatic_plans([_quarter_proposal()], now=NOW)
        assert store.get_plan(2) == manual
    asyncio.run(run())
