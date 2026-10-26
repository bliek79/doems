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
        "handoff_phase": "original_validator_observation_only",
        "physical_execution_enabled": False,
        "execution_permitted": False,
    }
