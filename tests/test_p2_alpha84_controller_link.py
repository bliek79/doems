"""Original Alpha84 final-validation interface is used, never substituted."""
import pytest
from types import SimpleNamespace
from custom_components.doems.alpha84_controller_link import inspect_alpha84_controller
from custom_components.doems.alpha84_handoff_contract import HandoffContractError


class Alpha84Validator:
    def __init__(self):
        self.inputs = []
        self._coordinator = SimpleNamespace(safety_guard=SimpleNamespace(evaluate=lambda data: {"safety_safe": True, "safety_reasons": []}))
    def evaluate_final_revalidation(self, data):
        self.inputs.append(data)
        return {"auto_final_revalidation_safe": False, "auto_final_revalidation_reasons": ["prestart_safe"]}


def args():
    return (
        {"selected_slot": 1, "selected_lifecycle": "pending", "selected_action": "laden", "safety_status": "safe", "safety_blockers": []},
        {"lifecycle_status": "pending", "origin": "automatic", "planner_identity": "alpha84-x", "action": "laden", "power_w": 500, "target_soc": 85, "max_runtime_h": 1.0},
    )


def verified_evidence():
    _, slot = args()
    evidence = {
        "scheduler_ready": True, "scheduler_selected_slot": 1,
        "scheduler_slots": {1: {
            "action": slot["action"], "power_w": slot["power_w"],
            "target_soc": float(slot["target_soc"]),
            "max_runtime_h": float(slot["max_runtime_h"]),
            "planner_identity": slot["planner_identity"],
        }},
        "execution_active": False, "physical_test_active": False,
    }
    for key in (
        "auto_prestart_safe", "auto_safety_handoff_safe",
        "auto_prestart_current_identity_match",
        "auto_prestart_current_signature_match",
        "forecast_ready", "control_path_configured",
    ):
        evidence[key] = True
    return evidence


def test_original_controller_is_invoked_for_observation_only():
    controller = Alpha84Validator()
    decision, slot = args()
    result = inspect_alpha84_controller(
        controller, decision, slot, sources_fresh=True, safety_safe=True,
        live_evidence=verified_evidence(),
    )
    assert len(controller.inputs) == 1
    assert controller.inputs[0]["scheduler_slots"][1]["power_w"] == 500
    assert controller.inputs[0]["auto_shadow_execution_permitted"] is False
    assert result["execution_permitted"] is False
    assert result["physical_execution_enabled"] is False
    assert result["validation"]["auto_final_revalidation_safe"] is False


@pytest.mark.parametrize("field", [
    "auto_prestart_safe", "auto_safety_handoff_safe",
    "auto_prestart_current_identity_match",
    "auto_prestart_current_signature_match",
    "forecast_ready", "control_path_configured",
])
def test_missing_or_false_alpha84_gate_blocks_without_invoking_validator(field):
    decision, slot = args()
    evidence = verified_evidence()
    evidence[field] = False
    controller = Alpha84Validator()
    with pytest.raises(HandoffContractError):
        inspect_alpha84_controller(
            controller, decision, slot, sources_fresh=True, safety_safe=True,
            live_evidence=evidence,
        )
    assert controller.inputs == []


@pytest.mark.parametrize("field", ["action", "power_w", "target_soc", "max_runtime_h", "planner_identity"])
def test_alpha84_original_plan_mismatch_blocks(field):
    decision, slot = args()
    evidence = verified_evidence()
    evidence["scheduler_slots"][1][field] = "mismatch"
    with pytest.raises(HandoffContractError, match="selection differs"):
        inspect_alpha84_controller(
            Alpha84Validator(), decision, slot,
            sources_fresh=True, safety_safe=True, live_evidence=evidence,
        )


@pytest.mark.parametrize("field,value", [
    ("execution_active", True), ("physical_test_active", True),
    ("scheduler_ready", False), ("scheduler_selected_slot", 2),
])
def test_original_controller_conflict_blocks(field, value):
    decision, slot = args()
    evidence = verified_evidence()
    evidence[field] = value
    with pytest.raises(HandoffContractError):
        inspect_alpha84_controller(
            Alpha84Validator(), decision, slot,
            sources_fresh=True, safety_safe=True, live_evidence=evidence,
        )


def test_missing_original_controller_blocks():
    decision, slot = args()
    with pytest.raises(HandoffContractError, match="unavailable"):
        inspect_alpha84_controller(None, decision, slot, sources_fresh=True, safety_safe=True, live_evidence={"soc": 60})


def test_missing_live_evidence_blocks():
    decision, slot = args()
    with pytest.raises(HandoffContractError, match="evidence"):
        inspect_alpha84_controller(Alpha84Validator(), decision, slot, sources_fresh=True, safety_safe=True, live_evidence={})


def test_original_safety_guard_blocks_before_final_validation():
    controller = Alpha84Validator()
    controller._coordinator.safety_guard.evaluate = lambda data: {
        "safety_safe": False, "safety_reasons": ["minimum_soc_reached"]
    }
    decision, slot = args()
    with pytest.raises(HandoffContractError, match="minimum_soc_reached"):
        inspect_alpha84_controller(
            controller, decision, slot, sources_fresh=True,
            safety_safe=True, live_evidence=verified_evidence(),
        )
    assert controller.inputs == []
