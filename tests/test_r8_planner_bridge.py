"""R8 read-only planner bridge contract tests."""
import importlib.util
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "custom_components/doems/execution_planner_bridge.py"
spec = importlib.util.spec_from_file_location("r8_planner_bridge", path)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_matching_manual_plan_is_observation_only():
    scheduler = {"selected_slot": 1, "selected_origin": "manual",
                 "selected_action": "laden", "selected_lifecycle": "pending"}
    plan = {"origin": "manual", "action": "laden",
            "lifecycle_status": "pending", "lifecycle_updated_at": "v1"}
    result = bridge.inspect_selection(scheduler, plan)
    assert result["ready"] is True
    assert result["execution_authority"] is False
    assert result["physical_execution_enabled"] is False


def test_missing_plan_blocks():
    result = bridge.inspect_selection({"selected_slot": 1}, None)
    assert result["ready"] is False
    assert "selected_plan_missing" in result["blockers"]


def test_selected_action_mismatch_blocks():
    result = bridge.inspect_selection(
        {"selected_slot": 1, "selected_origin": "manual",
         "selected_action": "ontladen", "selected_lifecycle": "pending"},
        {"origin": "manual", "action": "laden", "lifecycle_status": "pending"})
    assert "selected_action_changed" in result["blockers"]


def test_automatic_planner_identity_mismatch_blocks():
    result = bridge.inspect_selection(
        {"selected_slot": 2, "selected_origin": "automatic_72h_planner",
         "selected_action": "laden", "selected_lifecycle": "pending",
         "selected_planner_identity": "B"},
        {"origin": "automatic_72h_planner", "action": "laden",
         "lifecycle_status": "pending", "planner_identity": "A"})
    assert "planner_identity_changed" in result["blockers"]
