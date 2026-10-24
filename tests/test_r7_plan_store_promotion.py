"""R7 guarded Plan Store promotion and frozen R6 lifecycle regressions."""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from test_r6_slot_store import FakeHass, _candidates, _store_class


def args_for(plan, when):
    return {
        "expected_identity": plan["planner_identity"],
        "expected_signature": plan["planner_signature"],
        "expected_updated_at": plan.get("lifecycle_updated_at"),
        "gate_approved": True, "now": when,
    }


def test_pending_identity_origin_stable_and_persistent(monkeypatch):
    Store = _store_class(monkeypatch)

    async def verify():
        hass = FakeHass()
        store = Store(hass, "r7")
        await store.async_sync_automatic_plans(_candidates())
        old = store.get_plan(1)
        begin = datetime.fromisoformat(old["start_time"])
        manual_events, view_events = [], []
        store.add_manual_listener(lambda: manual_events.append(True))
        store.add_listener(lambda: view_events.append(True))
        assert not await store.async_promote_automatic_plan(
            1, **args_for(old, begin - timedelta(seconds=1))
        )
        assert not await store.async_promote_automatic_plan(
            1, **{**args_for(old, begin), "gate_approved": False}
        )
        assert await store.async_promote_automatic_plan(1, **args_for(old, begin))
        result = store.get_plan(1)
        assert result["lifecycle_status"] == "pending"
        assert result["origin"] == "automatic_72h_planner"
        assert result["planner_identity"] == old["planner_identity"]
        assert result["planner_signature"] == old["planner_signature"]
        assert result["lifecycle_reason"] == "r7_scheduler_prestart_safe"
        assert not manual_events
        assert len(view_events) == 1
        assert not await store.async_promote_automatic_plan(1, **args_for(old, begin))
        assert len(view_events) == 1
        reloaded = Store(hass, "r7")
        await reloaded.async_load()
        assert reloaded.get_plan(1)["lifecycle_status"] == "pending"
    asyncio.run(verify())


def test_stale_signature_or_manual_claim_cannot_promote(monkeypatch):
    Store = _store_class(monkeypatch)

    async def verify():
        store = Store(FakeHass(), "r7")
        await store.async_sync_automatic_plans(_candidates())
        original = store.get_plan(2)
        start = datetime.fromisoformat(original["start_time"])
        stale = {**args_for(original, start), "expected_signature": "outdated"}
        assert not await store.async_promote_automatic_plan(2, **stale)
        await store.async_set_value(2, "power_w", 400)
        manual = store.get_plan(2)
        assert manual["origin"] == "manual"
        assert not await store.async_promote_automatic_plan(2, **args_for(original, start))
        assert store.get_plan(2) == manual
    asyncio.run(verify())


def test_auto_pending_still_expires_by_r6_not_r7(monkeypatch):
    Store = _store_class(monkeypatch)

    async def verify():
        store = Store(FakeHass(), "r7")
        await store.async_sync_automatic_plans(_candidates())
        old = store.get_plan(3)
        begin = datetime.fromisoformat(old["start_time"])
        end = begin + timedelta(minutes=old["max_start_delay_min"])
        assert await store.async_promote_automatic_plan(3, **args_for(old, end))
        expired = await store.async_release_expired_automatic_plans(now=end+timedelta(seconds=1))
        assert 3 in expired["released_slots"]  # R6 may expire other due slots together
        assert store.last_terminal_event(3)["reason"] == "automatic_start_window_expired"
    asyncio.run(verify())
