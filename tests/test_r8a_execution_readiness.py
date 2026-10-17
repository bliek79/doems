"""Contract tests for R8-A readiness: no device calls or execution claims."""
from datetime import datetime, timezone

from custom_components.doems.ems_execution_readiness import validate_execution_readiness


NOW = datetime(2026, 10, 17, 14, 5, tzinfo=timezone.utc)
PLAN = {
    "slot": 2, "action": "laden", "lifecycle_status": "pending",
    "origin": "manual", "lifecycle_updated_at": "2026-10-17T13:00:00+00:00",
    "start_time": "2026-10-17T14:00:00+00:00",
    "max_start_delay_min": 10, "power_w": 3000,
    "max_runtime_h": 0.5, "target_soc": 90,
}
R7 = {
    "scheduler_selected_slot": 2, "scheduler_ready": True,
    "safety_ready": True, "prestart_ready": True,
}


def check(plan=None, scheduler=None, **overrides):
    args = dict(slot=2, now=NOW, physical_execution_enabled=False, other_controller_active=False)
    args.update(overrides)
    return validate_execution_readiness(plan or PLAN, scheduler or R7, **args)


def test_physical_execution_disabled_is_a_blocker():
    result = check()
    assert result["ready"] is False
    assert "physical_execution_disabled" in result["blockers"]
    assert result["execution_performed"] is False


def test_other_controller_blocks_even_when_enabled():
    result = check(physical_execution_enabled=True, other_controller_active=True)
    assert "other_controller_active" in result["blockers"]
    assert result["ready"] is False


def test_expired_start_window_blocks():
    result = check(now=datetime(2026, 10, 17, 14, 11, tzinfo=timezone.utc))
    assert "outside_start_window" in result["blockers"]


def test_concept_cannot_be_executed():
    result = check(plan={**PLAN, "lifecycle_status": "concept"})
    assert "plan_not_pending" in result["blockers"]


def test_plan_identity_change_blocks():
    result = check(scheduler={**R7, "plan_identity": "different"})
    assert "plan_identity_changed" in result["blockers"]


def test_eligible_snapshot_only_reports_readiness():
    result = check(physical_execution_enabled=True)
    assert result["ready"] is True
    assert result["execution_performed"] is False
