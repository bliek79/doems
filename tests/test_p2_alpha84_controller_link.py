"""Original Alpha84 final-validation interface is used, never substituted."""
import pytest
from custom_components.doems.alpha84_controller_link import inspect_alpha84_controller
from custom_components.doems.alpha84_handoff_contract import HandoffContractError


class Alpha84Validator:
    def __init__(self):
        self.inputs = []
    def evaluate_final_revalidation(self, data):
        self.inputs.append(data)
        return {"auto_final_revalidation_safe": False, "auto_final_revalidation_reasons": ["prestart_safe"]}


def args():
    return (
        {"selected_slot": 1, "selected_lifecycle": "pending", "selected_action": "laden", "safety_status": "safe", "safety_blockers": []},
        {"lifecycle_status": "pending", "origin": "automatic", "planner_identity": "alpha84-x", "action": "laden", "power_w": 500, "target_soc": 85, "max_runtime_h": 1.0},
    )


def test_original_controller_is_invoked_for_observation_only():
    controller = Alpha84Validator()
    decision, slot = args()
    result = inspect_alpha84_controller(
        controller, decision, slot, sources_fresh=True, safety_safe=True,
        live_evidence={"auto_prestart_safe": False, "control_path_configured": False},
    )
    assert len(controller.inputs) == 1
    assert controller.inputs[0]["scheduler_slots"][1]["power_w"] == 500
    assert controller.inputs[0]["auto_shadow_execution_permitted"] is False
    assert result["execution_permitted"] is False
    assert result["physical_execution_enabled"] is False
    assert result["validation"]["auto_final_revalidation_safe"] is False


def test_missing_original_controller_blocks():
    decision, slot = args()
    with pytest.raises(HandoffContractError, match="unavailable"):
        inspect_alpha84_controller(None, decision, slot, sources_fresh=True, safety_safe=True, live_evidence={"soc": 60})


def test_missing_live_evidence_blocks():
    decision, slot = args()
    with pytest.raises(HandoffContractError, match="evidence"):
        inspect_alpha84_controller(Alpha84Validator(), decision, slot, sources_fresh=True, safety_safe=True, live_evidence={})
