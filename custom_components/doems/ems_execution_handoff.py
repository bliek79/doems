from __future__ import annotations

from typing import Any


_EXTERNAL_MODE = "third_party_control"


class DOEMSExecutionHandoff:
    """Evaluate Safety Guard -> Execution Controller handoff without actuating.

    Step 12.2 stops before Final Revalidation and before any mode-switch or
    physical service call. The automatic Plan72 path uses this handoff directly
    and does not pass through the manual/legacy Action Controller.
    """

    def evaluate(self, data: dict[str, Any]) -> dict[str, Any]:
        slot = data.get("auto_safety_handoff_selected_slot")
        slots = data.get("scheduler_slots", {}) or {}
        detail = slots.get(slot) or slots.get(str(slot)) or {}
        origin = str(detail.get("origin") or "manual")

        base = {
            "auto_execution_handoff_enabled": True,
            "auto_execution_handoff_required": False,
            "auto_execution_handoff_ready": False,
            "auto_execution_handoff_status": "not_required",
            "auto_execution_handoff_reason": "Geen door Safety Guard goedgekeurde automatische actie",
            "auto_execution_handoff_reasons": [],
            "auto_execution_handoff_warnings": [],
            "auto_execution_handoff_selected_slot": None,
            "auto_execution_handoff_planner_identity": None,
            "auto_execution_handoff_action": None,
            "auto_execution_handoff_power_w": None,
            "auto_execution_handoff_target_soc": None,
            "auto_execution_handoff_max_runtime_h": None,
            "auto_execution_handoff_safety_safe": bool(data.get("auto_safety_handoff_safe")),
            "auto_execution_handoff_control_path_configured": bool(data.get("control_path_configured")),
            "auto_execution_handoff_controller_idle": not bool(data.get("execution_active")),
            "auto_execution_handoff_physical_test_idle": not bool(data.get("physical_test_active")),
            "auto_execution_handoff_final_revalidation_required": True,
            "auto_execution_handoff_execution_permitted": False,
            "auto_execution_handoff_physical_control": False,
        }

        if (
            slot is None
            or data.get("auto_safety_handoff_required") is not True
            or origin != "automatic_72h_planner"
        ):
            return base

        reasons: list[str] = []
        warnings: list[str] = []
        action = detail.get("action")
        try:
            power_w = int(float(detail.get("power_w") or 0))
        except (TypeError, ValueError):
            power_w = 0
        try:
            target_soc = float(detail.get("target_soc") or 0)
        except (TypeError, ValueError):
            target_soc = 0.0
        try:
            max_runtime_h = float(detail.get("max_runtime_h") or 0)
        except (TypeError, ValueError):
            max_runtime_h = 0.0
        planner_identity = detail.get("planner_identity")

        if data.get("auto_safety_handoff_safe") is not True:
            reasons.append("safety_handoff_not_safe")
        if data.get("auto_prestart_safe") is not True:
            reasons.append("prestart_not_safe")
        if data.get("auto_prestart_current_identity_match") is not True:
            reasons.append("planner_identity_mismatch")
        if not planner_identity:
            reasons.append("planner_identity_missing")
        if action not in {"laden", "ontladen"}:
            reasons.append("invalid_action")

        max_power = (
            int(data.get("max_discharge_power_w") or 800)
            if action == "ontladen"
            else int(data.get("max_charge_power_w") or 800)
        )
        if not 100 <= power_w <= max_power:
            reasons.append("invalid_power")
        if not 5 <= target_soc <= 100:
            reasons.append("invalid_target_soc")
        if not 0.25 <= max_runtime_h <= 12:
            reasons.append("invalid_runtime")
        if not data.get("control_path_configured"):
            reasons.append("control_path_not_configured")
        if data.get("physical_test_active"):
            reasons.append("physical_test_active")
        if data.get("execution_active"):
            reasons.append("execution_already_active")

        if data.get("operating_mode") != _EXTERNAL_MODE:
            warnings.append("external_mode_switch_required")
        if data.get("auto_prestart_current_signature_match") is not True:
            warnings.append("planner_revision_changed")

        ready = len(reasons) == 0
        return {
            "auto_execution_handoff_enabled": True,
            "auto_execution_handoff_required": True,
            "auto_execution_handoff_ready": ready,
            "auto_execution_handoff_status": "ready_observe" if ready else "blocked",
            "auto_execution_handoff_reason": (
                "Execution Controller handoff is gereed voor finale live revalidatie; fysieke uitvoering vereist de Automatic Execution-arm"
                if ready
                else ", ".join(reasons)
            ),
            "auto_execution_handoff_reasons": reasons,
            "auto_execution_handoff_warnings": warnings,
            "auto_execution_handoff_selected_slot": slot,
            "auto_execution_handoff_planner_identity": planner_identity,
            "auto_execution_handoff_action": action,
            "auto_execution_handoff_power_w": power_w,
            "auto_execution_handoff_target_soc": target_soc,
            "auto_execution_handoff_max_runtime_h": max_runtime_h,
            "auto_execution_handoff_safety_safe": bool(data.get("auto_safety_handoff_safe")),
            "auto_execution_handoff_control_path_configured": bool(data.get("control_path_configured")),
            "auto_execution_handoff_controller_idle": not bool(data.get("execution_active")),
            "auto_execution_handoff_physical_test_idle": not bool(data.get("physical_test_active")),
            "auto_execution_handoff_final_revalidation_required": True,
            "auto_execution_handoff_execution_permitted": False,
            "auto_execution_handoff_physical_control": False,
        }
