"""R8 planner-to-execution model integration contract, shadow only."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "custom_components/doems/execution_model.py"
spec = importlib.util.spec_from_file_location("r8_execution_model_contract", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def plan(**changes):
    data = dict(action="laden", origin="manual", power_w=1200,
                target_soc=80, max_runtime_h=2, execution_mode="direct",
                lifecycle_status="pending", lifecycle_updated_at=NOW.isoformat())
    data.update(changes)
    return data


def scheduler(p, **changes):
    data = dict(selected_slot=1, selected_origin=p["origin"],
                selected_action=p["action"], selected_lifecycle=p["lifecycle_status"],
                selected_planner_identity=p.get("planner_identity"),
                safety_status="safe", safety_blockers=[],
                prestart_status="ready", prestart_blockers=[],
                physical_execution_enabled=False, execution_authority=False)
    data.update(changes)
    return data


def battery(**changes):
    data = dict(status="ready", direction_consistent=True,
                status_direction_consistent=True, soc_percent=50)
    data.update(changes)
    return data


def evaluate(p=None, s=None, b=None, **changes):
    p = plan() if p is None else p
    return module.evaluate_execution(
        now=NOW, scheduler=scheduler(p) if s is None else s,
        plan=p, battery=battery() if b is None else b,
        source_fresh=True, **changes)


def test_valid_manual_plan_stays_shadow_only():
    result = evaluate()
    assert result["execution_performed"] is False
    assert result["physical_execution_enabled"] is False
    assert result["execution_authority"] is False
    assert result["status"] != "actief"


def test_changed_selected_action_blocks():
    p = plan()
    result = evaluate(p=p, s=scheduler(p, selected_action="ontladen"))
    assert "selected_action_changed" in result["blockers"]


def test_automatic_plan_identity_change_blocks():
    p = plan(origin="automatic_72h_planner", execution_mode="gepland",
             start_time=NOW.isoformat(), max_start_delay_min=15, planner_identity="auto-A")
    result = evaluate(p=p, s=scheduler(p, selected_planner_identity="auto-B"))
    assert "planner_identity_changed" in result["blockers"]


def test_missing_selected_plan_blocks():
    p = plan()
    result = evaluate(p=None, s=scheduler(p, selected_slot=2))
    assert result["execution_performed"] is False


def test_stale_battery_blocks():
    p = plan()
    result = module.evaluate_execution(now=NOW, scheduler=scheduler(p),
        plan=p, battery=battery(), source_fresh=False)
    assert "battery_input_unavailable" in result["blockers"]


def test_scheduler_boundary_change_blocks():
    p = plan()
    result = evaluate(p=p, s=scheduler(p, physical_execution_enabled=True))
    assert "scheduler_boundary_changed" in result["blockers"]


def test_restart_reconciliation_remains_blocked():
    result = evaluate(previous=dict(status="geblokkeerd", safe_return_required=True))
    assert result["safe_return_required"] is True
    assert "restart_requires_reconciliation" in result["blockers"]


def test_running_plan_identity_change_requires_safe_return():
    p = plan()
    result = evaluate(previous=dict(status="actief", plan_identity="old-plan",
                                    started_at=NOW.isoformat()))
    assert result["execution_performed"] is False
    assert result["safe_return_required"] is True
    assert "active_plan_changed" in result["blockers"]
