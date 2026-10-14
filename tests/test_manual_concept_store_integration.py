"""Existing three-slot store: Manual concept expiry, persistence and R6 reuse."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from test_r6_slot_store import FakeHass, _candidates, _store_class
from test_r6_slot_bridge_model import NOW


def test_old_manual_concept_expires_once_persists_and_r6_reuses(monkeypatch):
    Store = _store_class(monkeypatch)

    async def run():
        hass = FakeHass()
        store = Store(hass, "manual_concept_fix")
        await store.async_set_value(2, "action", "laden")
        await store.async_set_value(2, "execution_mode", "gepland")
        await store.async_set_value(2, "start_time", (NOW - timedelta(days=2)).isoformat())
        await store.async_set_value(2, "max_start_delay_min", 10)
        assert store.get_plan(2)["origin"] == "manual"
        assert store.get_plan(2)["lifecycle_status"] == "concept"
        first = await store.async_release_expired_manual_plans(now=NOW)
        assert first["released_slots"] == [2]
        event = store.last_terminal_event(2)
        assert event["origin"] == "manual"
        assert event["previous_lifecycle_status"] == "concept"
        assert event["reason"] == "manual_concept_start_window_expired"
        assert event["released_reason"] == "manual_concept_expired_released"
        assert store.get_plan(2)["action"] == "geen"
        assert store.get_plan(2)["lifecycle_reason"] == "manual_concept_expired_released"
        assert (await store.async_release_expired_manual_plans(now=NOW))["released_slots"] == []
        assert len(store.last_terminal_events()) == 1
        after_restart = Store(hass, "manual_concept_fix")
        await after_restart.async_load()
        assert after_restart.last_terminal_event(2) == event
        assert after_restart.get_plan(2)["action"] == "geen"
        synced = await after_restart.async_sync_automatic_plans(_candidates(), now=NOW)
        assert 2 in synced["written_slots"]
        assert after_restart.get_plan(2)["origin"] == "automatic_72h_planner"

    asyncio.run(run())


def test_manual_pending_audit_reason_is_backward_compatible(monkeypatch):
    Store = _store_class(monkeypatch)

    async def run():
        store = Store(FakeHass(), "pending_unchanged")
        await store.async_set_value(1, "action", "laden")
        await store.async_set_value(1, "execution_mode", "gepland")
        await store.async_set_value(1, "start_time", (NOW - timedelta(hours=1)).isoformat())
        await store.async_mark_lifecycle(1, "pending", "scheduled_by_user")
        released = await store.async_release_expired_manual_plans(now=NOW)
        assert released["released_slots"] == [1]
        event = store.last_terminal_event(1)
        assert event["reason"] == "manual_start_window_expired"
        assert event["released_reason"] == "manual_expired_released"
        assert event["previous_lifecycle_status"] == "pending"
        assert store.get_plan(1)["lifecycle_reason"] == "manual_expired_released"
        synced = await store.async_sync_automatic_plans(_candidates(), now=NOW)
        assert 1 in synced["written_slots"]

    asyncio.run(run())


def test_no_expiry_for_incomplete_or_direct_or_automatic(monkeypatch):
    Store = _store_class(monkeypatch)

    async def run():
        store = Store(FakeHass(), "protected")
        await store.async_set_value(1, "action", "laden")
        # No start time: preserved
        await store.async_set_value(2, "action", "laden")
        await store.async_set_value(2, "start_time", (NOW - timedelta(days=2)).isoformat())
        # Direct mode: preserved
        result = await store.async_release_expired_manual_plans(now=NOW)
        assert not result["changed"]
        assert store.get_plan(1)["action"] == "laden"
        assert store.get_plan(2)["action"] == "laden"
        await store.async_sync_automatic_plans(_candidates(), now=NOW)
        assert store.get_plan(1)["origin"] == "manual"
        assert store.get_plan(2)["origin"] == "manual"
        assert store.get_plan(3)["origin"] == "automatic_72h_planner"

    asyncio.run(run())


def test_next_deadline_and_exact_window_then_expire(monkeypatch):
    Store = _store_class(monkeypatch)
    from custom_components.doems.manual_plan_lifecycle_model import next_manual_expiry_deadline

    async def run():
        store = Store(FakeHass(), "boundary")
        await store.async_set_value(1, "action", "laden")
        await store.async_set_value(1, "execution_mode", "gepland")
        await store.async_set_value(1, "start_time", (NOW + timedelta(minutes=5)).isoformat())
        await store.async_set_value(1, "max_start_delay_min", 10)
        deadline = NOW + timedelta(minutes=15)
        schedule = next_manual_expiry_deadline(
            [store.get_plan(i) for i in (1, 2, 3)], now=NOW
        )
        assert schedule["slot"] == 1
        assert schedule["deadline"] == deadline
        assert not (await store.async_release_expired_manual_plans(now=deadline))["changed"]
        result = await store.async_release_expired_manual_plans(
            now=deadline + timedelta(microseconds=1)
        )
        assert result["released_slots"] == [1]

    asyncio.run(run())


def test_automatic_origin_is_never_released_by_manual_lifecycle(monkeypatch):
    Store = _store_class(monkeypatch)

    async def run():
        store = Store(FakeHass(), "automatic_preserved")
        await store.async_sync_automatic_plans(_candidates(), now=NOW)
        before = [store.get_plan(i) for i in (1, 2, 3)]
        result = await store.async_release_expired_manual_plans(
            now=NOW + timedelta(days=10)
        )
        assert not result["changed"]
        assert [store.get_plan(i) for i in (1, 2, 3)] == before

    asyncio.run(run())
