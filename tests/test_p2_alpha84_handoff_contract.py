"""Step 2: Combined plan is projected without granting physical authority."""
import pytest
from custom_components.doems.alpha84_handoff_contract import (
    HandoffContractError, project_combined_slot,
)


def good():
    return ({"selected_slot": 2, "selected_lifecycle": "pending", "selected_action": "laden", "safety_status": "safe", "safety_blockers": []},
            {"lifecycle_status": "pending", "origin": "automatic_72h_planner", "planner_identity": "plan-2",
             "action": "laden", "power_w": 500, "target_soc": 80,
             "max_runtime_h": 2.0, "start_time": "2026-10-26T12:00:00+00:00"})


def test_legacy_envelope_preserves_plan_but_never_grants_execution():
    decision, slot = good()
    result = project_combined_slot(decision, slot, sources_fresh=True, safety_safe=True)
    assert result["scheduler_selected_slot"] == 2
    assert result["scheduler_slots"][2]["origin"] == "automatic_72h_planner"
    assert result["scheduler_slots"][2]["planner_identity"] == "plan-2"
    assert result["scheduler_slots"][2]["power_w"] == 500
    assert result["auto_shadow_execution_permitted"] is False
    assert result["auto_final_revalidation_safe"] is False
    assert result["auto_mode_switch_preview_ready"] is False
    assert result["physical_execution_enabled"] is False


@pytest.mark.parametrize("field,value", [
    ("lifecycle_status", "actief"), ("origin", "other"),
    ("planner_identity", None), ("action", "ontladen"),
    ("power_w", 3501), ("power_w", True), ("target_soc", 101),
    ("max_runtime_h", 0.1),
])
def test_bad_slot_blocked(field, value):
    decision, slot = good()
    slot[field] = value
    with pytest.raises(HandoffContractError):
        project_combined_slot(decision, slot, sources_fresh=True, safety_safe=True)


@pytest.mark.parametrize("field,value", [
    ("selected_slot", 4), ("selected_slot", True),
    ("selected_action", "ontladen"), ("safety_status", "blocked"),
    ("selected_lifecycle", "actief"), ("safety_blockers", ["unsafe"]),
])
def test_bad_decision_blocked(field, value):
    decision, slot = good()
    decision[field] = value
    with pytest.raises(HandoffContractError):
        project_combined_slot(decision, slot, sources_fresh=True, safety_safe=True)


@pytest.mark.parametrize("fresh,safe", [(False, True), (True, False), (False, False)])
def test_missing_safety_evidence_blocked(fresh, safe):
    decision, slot = good()
    with pytest.raises(HandoffContractError):
        project_combined_slot(decision, slot, sources_fresh=fresh, safety_safe=safe)
