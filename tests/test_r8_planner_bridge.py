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


def test_real_r7_scheduler_selection_matches_plan():
    scheduler = {"scheduler_selected_slot": 2, "scheduler_selected_action": "laden",
                 "scheduler_ready": True,
                 "scheduler_slots": {2: {"slot": 2, "action": "laden", "origin": "automatic_72h_planner",
                                         "lifecycle_status": "pending", "selected": True,
                                         "status": "startklaar", "planner_identity": "cycle-1"}}}
    plan = {"slot": 2, "origin": "automatic_72h_planner", "action": "laden",
            "lifecycle_status": "pending", "planner_identity": "cycle-1"}
    result = bridge.inspect_selection(scheduler, plan)
    assert result["ready"] is True
    assert result["execution_authority"] is False


def test_real_r7_scheduler_not_ready_blocks():
    scheduler = {"scheduler_selected_slot": 1, "scheduler_selected_action": "laden",
                 "scheduler_ready": False,
                 "scheduler_slots": {1: {"slot": 1, "action": "laden", "origin": "manual", "lifecycle_status": "pending", "selected": True, "status": "startklaar"}}}
    plan = {"slot": 1, "origin": "manual", "action": "laden", "lifecycle_status": "pending"}
    result = bridge.inspect_selection(scheduler, plan)
    assert "scheduler_not_ready" in result["blockers"]


def test_real_r7_mismatched_slot_blocks():
    scheduler = {"scheduler_selected_slot": 1, "scheduler_selected_action": "laden",
                 "scheduler_ready": True,
                 "scheduler_slots": {"1": {"origin": "manual", "lifecycle_status": "pending"}}}
    plan = {"slot": 2, "origin": "manual", "action": "laden", "lifecycle_status": "pending"}
    result = bridge.inspect_selection(scheduler, plan)
    assert "selected_slot_changed" in result["blockers"]


def test_missing_plan_action_fails_closed():
    scheduler = {"selected_slot": 1, "selected_origin": "manual",
                 "selected_action": None, "selected_lifecycle": "pending"}
    plan = {"origin": "manual", "lifecycle_status": "pending"}
    assert bridge.inspect_selection(scheduler, plan)["ready"] is False


def test_r7_ready_flag_without_selected_slot_evidence_blocks():
    scheduler = {"scheduler_selected_slot": 1, "scheduler_selected_action": "laden",
                 "scheduler_ready": True,
                 "scheduler_slots": {1: {"origin": "manual", "lifecycle_status": "pending",
                                         "selected": False, "status": "kandidaat"}}}
    plan = {"slot": 1, "origin": "manual", "action": "laden", "lifecycle_status": "pending"}
    result = bridge.inspect_selection(scheduler, plan)
    assert result["ready"] is False
    assert "scheduler_selection_not_confirmed" in result["blockers"]


def test_r7_selected_slot_detail_mismatch_blocks():
    scheduler = {"scheduler_selected_slot": 1, "scheduler_selected_action": "laden",
                 "scheduler_ready": True,
                 "scheduler_slots": {1: {"slot": 2, "action": "ontladen", "origin": "manual",
                                         "lifecycle_status": "pending", "selected": True,
                                         "status": "startklaar"}}}
    plan = {"slot": 1, "origin": "manual", "action": "laden", "lifecycle_status": "pending"}
    result = bridge.inspect_selection(scheduler, plan)
    assert result["ready"] is False
    assert "scheduler_slot_detail_mismatch" in result["blockers"]
