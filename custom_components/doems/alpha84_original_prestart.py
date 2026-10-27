"""Run the installed, original Alpha84 Pre-start Validator on DOEMS selection.

Read-only inspection. Planner candidates MUST originate from the current
original Anker coordinator snapshot; never inject a fake matching candidate.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any, Mapping

from .alpha84_handoff_contract import HandoffContractError


def inspect_original_prestart(
    coordinator: Any, projected: Mapping[str, Any], live: Mapping[str, Any],
    *, verified_doems_candidate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected = projected["scheduler_selected_slot"]
    detail = projected["scheduler_slots"][selected]
    identity = detail.get("planner_identity")
    revision = detail.get("planner_signature")
    if detail.get("origin") != "automatic_72h_planner":
        return {"status": "not_applicable_manual", "safe": False}
    if not isinstance(identity, str) or not identity or not isinstance(revision, str) or not revision:
        raise HandoffContractError("DOEMS automatic plan identity/revision absent")
    candidates = ([dict(verified_doems_candidate)] if verified_doems_candidate is not None
                  else list(live.get("auto_bridge_candidates") or []) + list(live.get("auto_bridge_slot_preview") or []))
    matches = [c for c in candidates if isinstance(c, dict) and c.get("planner_identity") == identity]
    if not matches:
        raise HandoffContractError("Original Alpha84 candidate for DOEMS plan missing")
    if len(matches) != 1:
        raise HandoffContractError("Ambiguous Alpha84 pre-start candidate identity")
    if any(c.get("planner_signature") != revision for c in matches):
        raise HandoffContractError("Original Alpha84 candidate revision stale")
    # Import the class from the ORIGINAL installed integration rather than
    # copying a validator or producing a positive verdict in DOEMS.
    if coordinator is None:
        raise HandoffContractError("Original Alpha84 coordinator unavailable")
    module_name = coordinator.__class__.__module__.rsplit(".", 1)[0] + ".prestart_validator"
    try:
        validator_cls = getattr(import_module(module_name), "AnkerEmsPreStartValidator", None)
    except (ImportError, AttributeError) as err:
        raise HandoffContractError("Original Alpha84 pre-start module unavailable") from err
    if validator_cls is None:
        raise HandoffContractError("Original Alpha84 Pre-start Validator unavailable")
    data = dict(live)
    source_evidence = {}
    if verified_doems_candidate is not None:
        proof = verified_doems_candidate.get("_doems_r6_proof")
        if (not isinstance(proof, dict)
                or proof.get("source") != "published_r6_bridge"
                or type(proof.get("planner_generation")) is not int
                or proof["planner_generation"] < 0
                or proof.get("planner_valid") is not True
                or proof.get("bridge_ready") is not True
                or type(proof.get("invalid_candidate_count")) is not int
                or proof["invalid_candidate_count"] != 0
                or not doems_sources_fresh or not doems_safety_safe):
            raise HandoffContractError("Verified DOEMS R5/R6/R7 safety evidence incomplete")
        # The original validator evaluates the validated DOEMS 72h source,
        # not the unrelated legacy planner's boolean flags.
        source_evidence = {
            "auto_plan_72h_valid": proof["planner_valid"],
            "auto_bridge_valid": proof["bridge_ready"],
            "auto_bridge_invalid_candidate_count": proof["invalid_candidate_count"],
            "auto_plan_72h_execution_buffer_safe": bool(doems_safety_safe),
            "forecast_ready": bool(doems_sources_fresh),
        }
        data.update(source_evidence)
        data["auto_bridge_candidates"] = [dict(verified_doems_candidate)]
        data["auto_bridge_slot_preview"] = []
    data.update({
        "scheduler_ready": projected["scheduler_ready"],
        "scheduler_selected_slot": selected,
        "scheduler_slots": projected["scheduler_slots"],
    })
    result = validator_cls().evaluate(data)
    if not isinstance(result, dict) or result.get("auto_prestart_safe") is not True:
        reasons = result.get("auto_prestart_reasons") if isinstance(result, dict) else None
        raise HandoffContractError(f"Original Alpha84 pre-start blocked: {reasons}")
    if result.get("auto_prestart_current_identity_match") is not True or result.get("auto_prestart_current_signature_match") is not True:
        raise HandoffContractError("Original Alpha84 pre-start plan identity stale")
    return {"status": "original_prestart_safe_observe", "safe": True,
            "identity": identity, "revision": revision, "verdict": result,
            "physical_execution_enabled": False,
            "source_evidence": source_evidence}
