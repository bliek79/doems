"""Contract tests for observational Alpha84-aware three-slot matching."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "custom_components/doems/plan_slot_assignment.py"
spec = importlib.util.spec_from_file_location("slot_assignment_ch7", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self, plans):
        self.plans = plans

    def get_plan(self, slot):
        return self.plans[slot]


def plan(origin="manual", action="geen", lifecycle="concept", identity=None):
    return {"origin": origin, "action": action, "lifecycle_status": lifecycle,
            "planner_identity": identity, "start_time": "2026-10-30T15:00:00+00:00"}


def bridge(*names):
    return {"valid": True, "status": "ready",
            "source_plan_generation": 54, "source_input_fingerprint": "f" * 64,
            "eligible_candidates": [
                {"valid": True, "selection_status": "eligible", "planner_identity": name,
                 "start_time": "2026-10-30T15:00:00+00:00"} for name in names]}


def test_three_available_slots_and_overflow():
    store = Store({i: plan() for i in range(1, 4)})
    result = module.slot_assignment(store, bridge("a", "b", "c", "d"), now=NOW)
    assert [x["planner_identity"] for x in result["desired"].values()] == ["a", "b", "c"]
    assert result["unassigned"] == [{"identity": "d", "reason": "no_free_slot"}]


def test_manual_action_protected_and_matching_automatic_identity_retained():
    store = Store({1: plan(action="laden"), 2: plan(origin="automatic_72h_planner", action="laden",
                                                   lifecycle="pending", identity="b"), 3: plan()})
    result = module.slot_assignment(store, bridge("b", "c"), now=NOW)
    assert result["desired"][2]["planner_identity"] == "b"
    assert result["desired"][3]["planner_identity"] == "c"
    assert 1 not in result["desired"]


def test_due_pending_action_not_replaced():
    store = Store({1: plan(origin="automatic_72h_planner", action="laden", lifecycle="pending"),
                   2: plan(), 3: plan()})
    store.plans[1]["start_time"] = "2026-10-30T11:00:00+00:00"
    result = module.slot_assignment(store, bridge("a"), now=NOW)
    assert 1 not in result["desired"]


def test_invalid_bridge_fails_closed():
    store = Store({i: plan() for i in range(1, 4)})
    b = bridge("a")
    b["valid"] = False
    assert module.slot_assignment(store, b, now=NOW)["desired"] == {}


def test_manual_terminal_not_automatically_reused():
    store = Store({1: plan(action="laden", lifecycle="voltooid"),
                   2: plan(action="geladen", lifecycle="concept"),
                   3: plan()})
    result = module.slot_assignment(store, bridge("a"), now=NOW)
    assert list(result["desired"]) == [3]
