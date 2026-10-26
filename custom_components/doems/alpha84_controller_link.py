"""Strict connection to the *original* Alpha84 controller interface.

The controller is supplied, never recreated or replaced.  This adapter does
not call its actuation methods, alter its state, or grant authority.
"""
from __future__ import annotations

from typing import Any, Mapping

from .alpha84_handoff_contract import project_combined_slot, HandoffContractError


def inspect_alpha84_controller(
    original_controller: Any,
    decision: Mapping[str, Any],
    slot: Mapping[str, Any],
    *,
    sources_fresh: bool,
    safety_safe: bool,
    live_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Project Combined and run Alpha84's unchanged final validator, fail closed.

    A real instance of AnkerEmsExecutionController must be supplied.  Neither
    a planner decision nor this result can arm or start physical execution.
    """
    envelope = project_combined_slot(
        decision, slot, sources_fresh=sources_fresh, safety_safe=safety_safe
    )
    if original_controller is None:
        raise HandoffContractError("Original Alpha84 controller unavailable")
    if type(live_evidence) is not dict or not live_evidence:
        raise HandoffContractError("Fresh original-controller safety evidence unavailable")
    final_validator = getattr(original_controller, "evaluate_final_revalidation", None)
    if not callable(final_validator):
        raise HandoffContractError("Original Alpha84 final safety validator unavailable")
    # Run the original read-only Safety Guard against the projected DOEMS
    # selection and ORIGINAL live telemetry; never reuse its prior verdict.
    coordinator = getattr(original_controller, "_coordinator", None)
    guard = getattr(coordinator, "safety_guard", None)
    pre_mode = live_evidence.get("operating_mode") != "third_party_control"
    method = "evaluate_automatic_handoff" if pre_mode else "evaluate"
    evaluate = getattr(guard, method, None)
    if not callable(evaluate):
        raise HandoffContractError(f"Original Alpha84 Safety Guard phase unavailable: {method}")
    observed = dict(live_evidence)
    observed["scheduler_selected_slot"] = envelope["scheduler_selected_slot"]
    observed["scheduler_slots"] = envelope["scheduler_slots"]
    observed["scheduler_ready"] = envelope["scheduler_ready"]
    guard_result = evaluate(observed)
    verdict_key = "auto_safety_handoff_safe" if pre_mode else "safety_safe"
    if not isinstance(guard_result, dict) or guard_result.get(verdict_key) is not True:
        reasons_key = "auto_safety_handoff_reasons" if pre_mode else "safety_reasons"
        reasons = guard_result.get(reasons_key) if isinstance(guard_result, dict) else None
        raise HandoffContractError(f"Original Alpha84 Safety Guard blocked: {reasons}")
    # A DOEMS plan must not replace the original Alpha84 live Safety Guard
    # and pre-start verdicts. Original evidence must explicitly exist.
    for key in (
        "auto_prestart_safe",
        "auto_safety_handoff_safe",
        "auto_prestart_current_identity_match",
        "auto_prestart_current_signature_match",
        "forecast_ready",
        "control_path_configured",
    ):
        if live_evidence.get(key) is not True:
            raise HandoffContractError(f"Original Alpha84 safety source not safe: {key}")
    if live_evidence.get("execution_active") is not False:
        raise HandoffContractError("Original execution not confirmed idle")
    if live_evidence.get("physical_test_active") is not False:
        raise HandoffContractError("Original physical test not confirmed idle")
    # Alpha84 must already recognize the SAME plan and identity. The DOEMS
    # adapter may not manufacture a safe selection from unrelated old state.
    selected = envelope["scheduler_selected_slot"]
    if live_evidence.get("scheduler_ready") is not True or live_evidence.get("scheduler_selected_slot") != selected:
        raise HandoffContractError("Original scheduler has not accepted the selected slot")
    existing = (live_evidence.get("scheduler_slots") or {})
    old_slot = existing.get(selected) or existing.get(str(selected)) or {}
    new_slot = envelope["scheduler_slots"][selected]
    for field in ("action", "power_w", "target_soc", "max_runtime_h", "planner_identity", "planner_signature"):
        if old_slot.get(field) != new_slot.get(field):
            raise HandoffContractError(f"Original scheduler selection differs: {field}")
    data = dict(live_evidence)
    # Transfer only the selected plan input.  Do NOT synthesize any successful
    # prestart, safety, controller, mode or writer-authority state.
    for key in ("scheduler_selected_slot", "scheduler_slots", "scheduler_ready",
                "auto_final_revalidation_selected_slot"):
        data[key] = envelope[key]
    data["auto_execution_handoff_selected_slot"] = envelope["scheduler_selected_slot"]
    # Keep execution disabled even if the caller claims these flags true.
    data["auto_shadow_execution_permitted"] = False
    result = final_validator(data)
    if not isinstance(result, dict):
        raise HandoffContractError("Original validator returned invalid result")
    return {
        "source": "original_alpha84_execution_controller",
        "validation": result,
        "original_safety_guard": guard_result,
        "handoff_phase": "original_validator_observation_only",
        "physical_execution_enabled": False,
        "execution_permitted": False,
    }
