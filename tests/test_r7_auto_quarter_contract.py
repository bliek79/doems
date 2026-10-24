"""Pure edge cases for the unchanged R6 Automatic 15-minute contract."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from test_r7_r6_quarter_chain import _quarter_proposal
from test_r7_scheduler_prestart import model as r7, battery, bundle
from custom_components.doems.automatic_plan_contract import validate_automatic_plan


def test_r6_quarter_is_exact_boundary_and_10_minute_window():
    plan = _quarter_proposal()
    start = datetime.fromisoformat(plan["start_time"])
    for now in (start, start + timedelta(minutes=10)):
        assert validate_automatic_plan(plan, now=now, require_due=True) == []
    assert "start_not_reached" in validate_automatic_plan(
        plan, now=start-timedelta(microseconds=1), require_due=True
    )
    assert "start_window_expired" in validate_automatic_plan(
        plan, now=start+timedelta(minutes=10, microseconds=1), require_due=True
    )


def test_fractional_quarter_and_contract_mismatch_rejected():
    plan = _quarter_proposal()
    for duration, expected in (
        (0.20, "max_runtime_out_of_range"),
        (0.375, "runtime_not_quarter_aligned"),
        (12.25, "max_runtime_out_of_range"),
    ):
        mutated = {**plan, "max_runtime_h": duration}
        assert expected in validate_automatic_plan(mutated)
    mutated = {**plan, "max_runtime_h": 0.5}
    assert "duration_end_mismatch" in validate_automatic_plan(mutated)
    mutated = {**plan, "planned_end_time": None}
    assert "planned_end_invalid" in validate_automatic_plan(mutated)


def test_prestart_rejects_nonquarter_and_invalid_r5_while_staying_non_actuating():
    plan = _quarter_proposal()
    start = datetime.fromisoformat(plan["start_time"])
    current = {"origin": plan["origin"], "lifecycle_status": "concept",
               "lifecycle_updated_at": "revision1", **plan}
    current["lifecycle_status"] = "concept"
    def evaluate(item, source=None):
        return r7.evaluate_r7(
            now=start, plans={1: item}, bundle=source or bundle(),
            battery=battery(), bridge_ready=True, planner_generation=5,
            source_fresh=True,
        )
    assert evaluate(current)["can_promote"]
    for invalid in (
        {**current, "max_runtime_h": 0.375},
        {**current, "planned_end_time": None},
    ):
        result = evaluate(invalid)
        assert not result["can_promote"]
        assert result["prestart_blockers"]
        assert not result["execution_authority"]
        assert not result["physical_execution_enabled"]
    bad = bundle()
    bad["planner_published_generation"] = 4
    assert not evaluate(current, bad)["can_promote"]
