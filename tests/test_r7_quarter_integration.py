"""End-to-end R6 -> three-slot Plan Store -> R7 prestart -> pending -> expiry.

This protects the accepted R6 15-minute automatic segments while preserving
Manual's independent 30-minute minimum and software-only R7 authority.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from test_r6_slot_bridge_model import NOW, _rows, _combined, _load_model
from test_r6_slot_store import FakeHass, _store_class
from test_r7_scheduler_prestart import model as r7, bundle, battery


def proposals(quarters=1):
    rows = _rows()
    for index in range(quarters):
        rows[index]["charge_from_grid_safety_kwh"] = 0.175
    result = _load_model().build_automatic_slot_proposals(_combined(rows), now=NOW)
    assert result["valid"] is True
    assert len(result["proposals"]) == 1
    return result["proposals"]


def r7_evaluate(plan, when, *, fresh=True):
    return r7.evaluate_r7(
        now=when, plans={1: plan}, bundle=bundle(), battery=battery(),
        bridge_ready=True, planner_generation=5, source_fresh=fresh,
    )


@pytest.mark.parametrize("quarters", [1, 2, 3])
def test_r6_quarter_plans_are_accepted_consistently_at_store_and_r7(monkeypatch, quarters):
    Store = _store_class(monkeypatch)

    async def run():
        source = proposals(quarters)[0]
        assert source["max_runtime_h"] == quarters * 0.25
        store = Store(FakeHass(), f"quarter_{quarters}")
        result = await store.async_sync_automatic_plans([source], now=NOW)
        assert result["written_slots"] == [1]
        plan = store.get_plan(1)
        assert plan["origin"] == "automatic_72h_planner"
        assert store.plan_status(1) == "concept"
        assert store.schedule_blockers(1) == []
        start = datetime.fromisoformat(source["start_time"])
        early = r7_evaluate(plan, start - timedelta(seconds=1))
        assert not early["can_promote"]
        at_start = r7_evaluate(plan, start)
        assert at_start["can_promote"]
        assert at_start["prestart_blockers"] == []
        await store.async_promote_automatic_plan(
            1, expected_identity=plan["planner_identity"],
            expected_signature=plan["planner_signature"],
            expected_updated_at=plan["lifecycle_updated_at"],
            gate_approved=at_start["can_promote"], now=start,
        )
        assert store.get_plan(1)["lifecycle_status"] == "pending"
        assert store.plan_status(1) == "gepland"
        assert store.schedule_blockers(1) == []
        assert store.get_plan(1)["origin"] == "automatic_72h_planner"
        persisted = Store(store.hass, f"quarter_{quarters}")
        await persisted.async_load()
        assert persisted.get_plan(1)["planner_identity"] == source["planner_identity"]
        assert persisted.get_plan(1)["lifecycle_status"] == "pending"
        deadline = start + timedelta(minutes=source["max_start_delay_min"])
        assert not (await persisted.async_release_expired_automatic_plans(now=deadline))["changed"]
        after = await persisted.async_release_expired_automatic_plans(now=deadline + timedelta(seconds=1))
        assert after["released_slots"] == [1]
        assert persisted.last_terminal_event(1)["planner_identity"] == source["planner_identity"]
    asyncio.run(run())


def test_manual_15_minute_plan_remains_invalid_manual_30_minute_plan_works(monkeypatch):
    Store = _store_class(monkeypatch)

    async def run():
        store = Store(FakeHass(), "manual")
        start = datetime.fromisoformat(proposals()[0]["start_time"])
        await store.async_set_value(2, "action", "laden")
        await store.async_set_value(2, "start_time", start.isoformat())
        await store.async_set_value(2, "max_runtime_h", 0.25)
        assert store.get_plan(2)["origin"] == "manual"
        assert "max_runtime_out_of_range" in store.schedule_blockers(2)
        with pytest.raises(ValueError, match="max_runtime_out_of_range"):
            await store.async_schedule(2)
        assert store.get_plan(2)["lifecycle_status"] == "concept"
        await store.async_set_value(2, "max_runtime_h", 0.5)
        assert store.schedule_blockers(2) == []
        await store.async_schedule(2)
        assert store.get_plan(2)["lifecycle_status"] == "pending"
        assert store.get_plan(2)["origin"] == "manual"
    asyncio.run(run())


def test_manual_takeover_blocks_r7_even_when_previous_auto_was_one_quarter(monkeypatch):
    Store = _store_class(monkeypatch)

    async def run():
        store = Store(FakeHass(), "claim")
        source = proposals()[0]
        await store.async_sync_automatic_plans([source], now=NOW)
        previous = store.get_plan(1)
        start = datetime.fromisoformat(previous["start_time"])
        await store.async_set_value(1, "power_w", 600)
        manual = store.get_plan(1)
        assert manual["origin"] == "manual"
        assert manual["lifecycle_status"] == "concept"
        assert not r7_evaluate(manual, start)["can_promote"]
        assert not await store.async_promote_automatic_plan(
            1, expected_identity=previous["planner_identity"],
            expected_signature=previous["planner_signature"],
            expected_updated_at=previous["lifecycle_updated_at"],
            gate_approved=True, now=start,
        )
        assert store.get_plan(1) == manual
    asyncio.run(run())


@pytest.mark.parametrize("runtime", [0.20, 0.30, 12.25])
def test_invalid_automatic_runtime_is_rejected_by_store_and_prestart(monkeypatch, runtime):
    Store = _store_class(monkeypatch)

    async def run():
        invalid = deepcopy(proposals()[0])
        invalid["max_runtime_h"] = runtime
        store = Store(FakeHass(), f"invalid_{runtime}")
        await store.async_sync_automatic_plans([invalid], now=NOW)
        start = datetime.fromisoformat(invalid["start_time"])
        current = store.get_plan(1)
        assert store.schedule_blockers(1)
        state = r7_evaluate(current, start)
        assert state["prestart_blockers"]
        assert state["can_promote"] is False
        assert not await store.async_promote_automatic_plan(
            1, expected_identity=current["planner_identity"],
            expected_signature=current["planner_signature"],
            expected_updated_at=current["lifecycle_updated_at"],
            gate_approved=True, now=start,
        )
        assert store.get_plan(1)["lifecycle_status"] == "concept"
    asyncio.run(run())


def test_inconsistent_end_and_stale_source_never_promote(monkeypatch):
    Store = _store_class(monkeypatch)

    async def run():
        p = proposals()[0]
        p["planned_end_time"] = (datetime.fromisoformat(p["planned_end_time"]) + timedelta(minutes=15)).isoformat()
        store = Store(FakeHass(), "end_mismatch")
        await store.async_sync_automatic_plans([p], now=NOW)
        assert "duration_end_mismatch" in store.schedule_blockers(1)
        start = datetime.fromisoformat(p["start_time"])
        assert not r7_evaluate(store.get_plan(1), start)["can_promote"]
        assert "battery_sources_stale" in r7_evaluate(store.get_plan(1), start, fresh=False)["safety_blockers"]
    asyncio.run(run())


def test_r7_contract_keeps_automatic_action_non_actuating(monkeypatch):
    Store = _store_class(monkeypatch)

    async def run():
        store = Store(FakeHass(), "no_actuator")
        await store.async_sync_automatic_plans(proposals(), now=NOW)
        start = datetime.fromisoformat(store.get_plan(1)["start_time"])
        result = r7_evaluate(store.get_plan(1), start)
        assert result["physical_execution_enabled"] is False
        assert result["execution_authority"] is False
        assert result["can_promote"]
    asyncio.run(run())
