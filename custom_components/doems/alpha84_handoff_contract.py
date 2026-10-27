"""Non-actuating DOEMS Combined -> Alpha84 scheduler input contract.

Pure projection only: no Home Assistant services, authority state changes,
or new execution algorithm. Alpha84 executor still owns all safety checks.
"""
from __future__ import annotations

from typing import Any, Mapping


class HandoffContractError(ValueError):
    """Plan cannot be represented safely for the legacy controller."""


def project_combined_slot(
    selection: Mapping[str, Any],
    slot: Mapping[str, Any],
    *,
    sources_fresh: bool,
    safety_safe: bool,
) -> dict[str, Any]:
    """Convert a single DOEMS slot into Alpha84's scheduler data envelope.

    The result deliberately *never* grants automatic or physical authority.
    This is a representation/validation contract, not execution permission.
    """
    number = selection.get("selected_slot")
    if type(number) is not int or number not in (1, 2, 3):
        raise HandoffContractError("No valid selected slot")
    if selection.get("selected_lifecycle") != "pending" or slot.get("lifecycle_status") != "pending":
        raise HandoffContractError("Plan is not pending")
    if selection.get("safety_status") != "safe" or selection.get("safety_blockers"):
        raise HandoffContractError("Scheduler safety is not clear")
    if not sources_fresh or not safety_safe:
        raise HandoffContractError("Input or safety evidence missing")
    action = slot.get("action")
    if action not in ("laden", "ontladen") or selection.get("selected_action") != action:
        raise HandoffContractError("Action changed or unsupported")
    if slot.get("origin") not in ("manual", "automatic_72h_planner"):
        raise HandoffContractError("Unknown plan origin")
    identity = slot.get("planner_identity") if slot.get("origin") == "automatic_72h_planner" else slot.get("lifecycle_updated_at")
    if not isinstance(identity, str) or not identity.strip():
        raise HandoffContractError("Plan identity missing")
    power = slot.get("power_w")
    if type(power) is not int or not 100 <= power <= 3500:
        raise HandoffContractError("Power invalid")
    target = slot.get("target_soc")
    runtime = slot.get("max_runtime_h")
    if type(target) not in (int, float) or not 5 <= target <= 100:
        raise HandoffContractError("Target SOC invalid")
    if type(runtime) not in (int, float) or not 0.25 <= runtime <= 12:
        raise HandoffContractError("Runtime invalid")
    if selection.get("selected_slot") != number:
        raise HandoffContractError("Selection changed")
    detail = {
        "action": action,
        "power_w": power,
        "target_soc": float(target),
        "max_runtime_h": float(runtime),
        "origin": "automatic_72h_planner" if slot["origin"] == "automatic_72h_planner" else "manual",
        "planner_identity": identity,
        "planner_signature": slot.get("planner_signature"),
        "start_time": slot.get("start_time"),
        "planned_energy_kwh": slot.get("planned_energy_kwh"),
        "planned_end_time": slot.get("planned_end_time"),
    }
    return {
        "scheduler_ready": True,
        "scheduler_selected_slot": number,
        "scheduler_slots": {number: detail},
        "auto_final_revalidation_selected_slot": number,
        # These MUST be established later by the unchanged Alpha84 safety
        # chain, not by a planning result or a UI toggle.
        "auto_shadow_execution_permitted": False,
        "auto_final_revalidation_safe": False,
        "auto_mode_switch_preview_ready": False,
        "physical_execution_enabled": False,
        "handoff_phase": "representation_only",
    }
