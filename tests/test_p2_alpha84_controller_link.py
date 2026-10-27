"""Original Alpha84 final-validation interface is used, never substituted."""
import pytest
import sys
import types
from types import SimpleNamespace
from custom_components.doems.alpha84_controller_link import inspect_alpha84_controller
from custom_components.doems.alpha84_handoff_contract import HandoffContractError


class Alpha84Validator:
    def __init__(self):
        self.inputs = []
        self._coordinator = SimpleNamespace(safety_guard=SimpleNamespace(evaluate=lambda data: {"safety_safe": True, "safety_reasons": []}, evaluate_automatic_handoff=lambda data: {"auto_safety_handoff_safe": True, "auto_safety_handoff_reasons": []}))
    def evaluate_final_revalidation(self, data):
        self.inputs.append(data)
        return {"auto_final_revalidation_safe": False, "auto_final_revalidation_reasons": ["prestart_safe"]}


@pytest.fixture(autouse=True)
def original_prestart_module(monkeypatch):
    from custom_components.doems import alpha84_original_prestart
    class OriginalPrestart:
        def evaluate(self, data):
            candidate = (data.get("auto_bridge_candidates") or [None])[0]
            detail = data["scheduler_slots"][data["scheduler_selected_slot"]]
            same = bool(candidate and candidate.get("planner_identity") == detail.get("planner_identity"))
            revision = bool(same and candidate.get("planner_signature") == detail.get("planner_signature"))
            return {
                "auto_prestart_safe": same and revision,
                "auto_prestart_current_identity_match": same,
                "auto_prestart_current_signature_match": revision,
                "auto_prestart_reasons": [] if same and revision else ["mismatch"],
            }
    module = types.SimpleNamespace(AnkerEmsPreStartValidator=OriginalPrestart)
    monkeypatch.setattr(alpha84_original_prestart, "import_module", lambda name: module)


def args():
    return (
        {"selected_slot": 1, "selected_lifecycle": "pending", "selected_action": "laden", "safety_status": "safe", "safety_blockers": []},
        {"lifecycle_status": "pending", "origin": "automatic_72h_planner", "planner_identity": "alpha84-x", "planner_signature": "base-revision", "action": "laden", "power_w": 500, "target_soc": 85, "max_runtime_h": 1.0},
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
            "planner_signature": slot.get("planner_signature"),
        }},
        "execution_active": False, "physical_test_active": False,
        "auto_bridge_candidates": [{"planner_identity": slot["planner_identity"], "planner_signature": slot.get("planner_signature"), "action": slot["action"], "power_w": slot["power_w"], "target_soc": float(slot["target_soc"])}],
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
    controller._coordinator.safety_guard.evaluate_automatic_handoff = lambda data: {
        "auto_safety_handoff_safe": False, "auto_safety_handoff_reasons": ["minimum_soc_reached"]
    }
    decision, slot = args()
    with pytest.raises(HandoffContractError, match="minimum_soc_reached"):
        inspect_alpha84_controller(
            controller, decision, slot, sources_fresh=True,
            safety_safe=True, live_evidence=verified_evidence(),
        )
    assert controller.inputs == []


def test_matching_revision_passed_to_original_validator():
    decision, slot = args()
    slot["planner_signature"] = "revision-42"
    evidence = verified_evidence()
    evidence["scheduler_slots"][1]["planner_signature"] = "revision-42"
    evidence["auto_bridge_candidates"][0]["planner_signature"] = "revision-42"
    controller = Alpha84Validator()
    inspect_alpha84_controller(controller, decision, slot, sources_fresh=True,
                               safety_safe=True, live_evidence=evidence)
    assert controller.inputs[0]["scheduler_slots"][1]["planner_signature"] == "revision-42"


def test_stale_revision_blocks():
    decision, slot = args()
    slot["planner_signature"] = "revision-new"
    evidence = verified_evidence()
    evidence["scheduler_slots"][1]["planner_signature"] = "revision-old"
    with pytest.raises(HandoffContractError, match="candidate mismatch: planner_signature"):
        inspect_alpha84_controller(Alpha84Validator(), decision, slot,
                                   sources_fresh=True, safety_safe=True, live_evidence=evidence)


def test_missing_original_prestart_candidate_blocks():
    decision, slot = args()
    evidence = verified_evidence()
    evidence["auto_bridge_candidates"] = []
    with pytest.raises(HandoffContractError, match="candidate"):
        inspect_alpha84_controller(
            Alpha84Validator(), decision, slot,
            sources_fresh=True, safety_safe=True, live_evidence=evidence,
        )


def test_stale_original_prestart_candidate_revision_blocks():
    decision, slot = args()
    evidence = verified_evidence()
    evidence["auto_bridge_candidates"][0]["planner_signature"] = "outdated"
    with pytest.raises(HandoffContractError, match="candidate mismatch: planner_signature"):
        inspect_alpha84_controller(
            Alpha84Validator(), decision, slot,
            sources_fresh=True, safety_safe=True, live_evidence=evidence,
        )


def test_duplicate_candidate_lineage_is_blocked():
    decision, slot = args()
    evidence = verified_evidence()
    evidence["auto_bridge_candidates"].append(dict(evidence["auto_bridge_candidates"][0]))
    with pytest.raises(HandoffContractError, match="one authoritative"):
        inspect_alpha84_controller(Alpha84Validator(), decision, slot,
                                   sources_fresh=True, safety_safe=True,
                                   live_evidence=evidence)


def test_changed_candidate_power_is_blocked():
    decision, slot = args()
    evidence = verified_evidence()
    evidence["auto_bridge_candidates"][0]["power_w"] = 700
    with pytest.raises(HandoffContractError, match="candidate mismatch: power_w"):
        inspect_alpha84_controller(Alpha84Validator(), decision, slot,
                                   sources_fresh=True, safety_safe=True,
                                   live_evidence=evidence)


def test_verified_r6_candidate_needs_no_matching_old_scheduler_plan():
    decision, slot = args()
    evidence = verified_evidence()
    evidence["scheduler_ready"] = False
    evidence["scheduler_selected_slot"] = None
    evidence["scheduler_slots"] = {}
    evidence["auto_bridge_candidates"] = []
    candidate = {
        "planner_identity": slot["planner_identity"],
        "planner_signature": slot["planner_signature"],
        "action": slot["action"], "power_w": slot["power_w"],
        "target_soc": float(slot["target_soc"]),
    }
    controller = Alpha84Validator()
    candidate["_doems_r6_proof"] = {
        "source": "published_r6_bridge", "planner_generation": 12,
        "bridge_ready": True, "planner_valid": True,
        "invalid_candidate_count": 0,
    }
    result = inspect_alpha84_controller(
        controller, decision, slot, sources_fresh=True, safety_safe=True,
        live_evidence=evidence, verified_doems_candidate=candidate,
    )
    assert result["plan_lineage"]["lineage"] == "matched_against_verified_r6_candidate"
    assert result["original_prestart"]["safe"] is True
    assert result["physical_execution_enabled"] is False
    assert result["execution_permitted"] is False


def test_verified_r6_candidate_with_wrong_power_fails_before_prestart():
    decision, slot = args()
    evidence = verified_evidence()
    candidate = {
        "planner_identity": slot["planner_identity"],
        "planner_signature": slot["planner_signature"],
        "action": slot["action"], "power_w": 750,
        "target_soc": float(slot["target_soc"]),
    }
    with pytest.raises(HandoffContractError, match="candidate mismatch: power_w"):
        inspect_alpha84_controller(
            Alpha84Validator(), decision, slot,
            sources_fresh=True, safety_safe=True, live_evidence=evidence,
            verified_doems_candidate=candidate,
        )


def test_unverified_r6_source_cannot_use_legacy_positive_72h_flags():
    decision, slot = args()
    evidence = verified_evidence()
    candidate = {
        "planner_identity": slot["planner_identity"],
        "planner_signature": slot["planner_signature"],
        "action": slot["action"], "power_w": slot["power_w"],
        "target_soc": float(slot["target_soc"]),
    }
    # No proof from the actual published R6 generation.
    with pytest.raises(HandoffContractError, match="R5/R6/R7 safety evidence"):
        inspect_alpha84_controller(
            Alpha84Validator(), decision, slot,
            sources_fresh=True, safety_safe=True,
            live_evidence=evidence, verified_doems_candidate=candidate,
        )
