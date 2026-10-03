"""Frozen Anker alpha76 automatic execution arm/gate semantics.

This module is a thin standalone extraction of AnkerEmsCoordinator
._automatic_execution_shadow().  It preserves the Alpha76 decision logic and
only adds read-only DOEMS aliases for the existing dashboard/runtime surface.
"""
from __future__ import annotations

from typing import Any


class DOEMSAutomaticExecutionGate:
    """Evaluate the frozen Alpha76 automatic physical-execution permission."""

    def evaluate(
        self,
        data: dict[str, Any],
        *,
        armed: bool,
        readiness: dict[str, Any],
    ) -> dict[str, Any]:
        slot = data.get("scheduler_selected_slot")
        slots = data.get("scheduler_slots", {}) or {}
        detail = slots.get(slot) or slots.get(str(slot)) or {}
        origin = str(detail.get("origin") or "manual")
        purpose = str(detail.get("purpose") or "")
        blockers: list[str] = []
        warnings: list[str] = []

        automatic_selected = bool(
            slot is not None
            and data.get("scheduler_ready")
            and origin == "automatic_72h_planner"
        )
        if not automatic_selected:
            blockers.append("no_automatic_action_selected")
        if data.get("auto_prestart_safe") is not True:
            blockers.append("prestart_not_safe")
        if data.get("auto_safety_handoff_safe") is not True:
            blockers.append("safety_handoff_not_safe")
        if data.get("auto_execution_handoff_ready") is not True:
            blockers.append("execution_handoff_not_ready")
        if data.get("auto_final_revalidation_safe") is not True:
            blockers.append("final_revalidation_not_safe")
        if data.get("auto_mode_switch_preview_ready") is not True:
            blockers.append("mode_switch_preview_not_ready")

        selected_action = str(detail.get("action") or "")
        safety_recovery_action = bool(
            selected_action == "laden"
            and purpose in {"veiligheidsladen", "veiligheidsladen+handelsladen"}
        )
        if (
            data.get("auto_plan_72h_execution_buffer_safe") is not True
            and not safety_recovery_action
        ):
            blockers.append("execution_buffer_unsafe")
        if data.get("forecast_ready") is not True:
            blockers.append("forecast_not_ready")
        if not data.get("control_path_configured"):
            blockers.append("control_path_not_configured")
        if data.get("physical_test_active"):
            blockers.append("physical_test_active")
        if data.get("execution_active"):
            blockers.append("execution_already_active")

        manual_override = bool(
            (
                slot is not None
                and data.get("scheduler_ready")
                and origin != "automatic_72h_planner"
            )
            or (
                data.get("execution_active")
                and str(data.get("execution_origin") or "manual")
                != "automatic_72h_planner"
            )
        )
        if manual_override:
            blockers.append("manual_override_active")

        is_trade = purpose in {
            "handelsladen",
            "veiligheidsladen+handelsladen",
            "handel_ontladen",
        }
        all_prices_known = bool(detail.get("all_prices_known"))
        if is_trade and not all_prices_known:
            blockers.append("trade_requires_known_prices")
        elif not all_prices_known:
            warnings.append("forecast_price_used_for_non_trade_planning")

        if readiness.get("ready") is not True:
            blockers.append("control_path_not_stable")

        blockers = list(dict.fromkeys(blockers))
        warnings = list(dict.fromkeys(warnings))
        technical_ready = not blockers
        execution_permitted = bool(automatic_selected and technical_ready and armed)
        if not automatic_selected:
            status = "idle"
        elif not technical_ready:
            status = "blocked"
        elif not armed:
            status = "ready_disarmed"
        else:
            status = "armed_live_ready"

        result = {
            "auto_shadow_enabled": True,
            "auto_shadow_status": status,
            "auto_shadow_technical_ready": technical_ready,
            "auto_shadow_armed": bool(armed),
            "auto_shadow_execution_permitted": execution_permitted,
            "auto_shadow_physical_control": execution_permitted,
            "auto_shadow_selected_slot": slot if automatic_selected else None,
            "auto_shadow_planner_identity": detail.get("planner_identity") if automatic_selected else None,
            "auto_shadow_action": detail.get("action") if automatic_selected else None,
            "auto_shadow_purpose": purpose or None,
            "auto_shadow_power_w": detail.get("power_w") if automatic_selected else None,
            "auto_shadow_target_soc": detail.get("target_soc") if automatic_selected else None,
            "auto_shadow_max_runtime_h": detail.get("max_runtime_h") if automatic_selected else None,
            "auto_shadow_start_time": detail.get("start_time") if automatic_selected else None,
            "auto_shadow_price_sources": list(detail.get("price_sources") or []),
            "auto_shadow_all_prices_known": all_prices_known,
            "auto_shadow_manual_override_active": manual_override,
            "auto_shadow_blockers": blockers,
            "auto_shadow_warnings": warnings,
            "auto_shadow_control_path_ready": bool(readiness.get("ready")),
            "auto_shadow_control_path_reason": readiness.get("reason"),
            "auto_shadow_control_path_stable_seconds": readiness.get("stable_seconds", 0),
            "auto_shadow_pre_mode_ready": bool(readiness.get("pre_mode_ready")),
            "auto_shadow_pre_mode_reason": readiness.get("pre_mode_reason"),
            "auto_shadow_pre_mode_stable_seconds": readiness.get("pre_mode_stable_seconds", 0),
            "auto_shadow_post_mode_ready": bool(readiness.get("post_mode_ready")),
            "auto_shadow_post_mode_reason": readiness.get("post_mode_reason"),
            "auto_shadow_post_mode_stable_seconds": readiness.get("post_mode_stable_seconds", 0),
            "auto_shadow_post_mode_required": bool(readiness.get("post_mode_required")),
            "auto_shadow_control_entities": readiness.get("entities", {}),
            "auto_shadow_note": (
                "Alpha76: een gewapende, volledig veilige automatische planneractie "
                "mag fysiek worden uitgevoerd. Two-stage control-path readiness, "
                "post-mode revalidatie en fail-safe stop blijven verplicht."
            ),
        }

        # Read-only compatibility aliases for the existing DOEMS alpha31 surface.
        result.update({
            "auto_execution_gate_enabled": result["auto_shadow_enabled"],
            "auto_execution_gate_status": result["auto_shadow_status"],
            "auto_execution_gate_technical_ready": result["auto_shadow_technical_ready"],
            "auto_execution_gate_armed": result["auto_shadow_armed"],
            "auto_execution_gate_execution_permitted": result["auto_shadow_execution_permitted"],
            "auto_execution_gate_selected_slot": result["auto_shadow_selected_slot"],
            "auto_execution_gate_planner_identity": result["auto_shadow_planner_identity"],
            "auto_execution_gate_action": result["auto_shadow_action"],
            "auto_execution_gate_purpose": result["auto_shadow_purpose"],
            "auto_execution_gate_power_w": result["auto_shadow_power_w"],
            "auto_execution_gate_target_soc": result["auto_shadow_target_soc"],
            "auto_execution_gate_max_runtime_h": result["auto_shadow_max_runtime_h"],
            "auto_execution_gate_price_sources": result["auto_shadow_price_sources"],
            "auto_execution_gate_all_prices_known": result["auto_shadow_all_prices_known"],
            "auto_execution_gate_manual_override_active": result["auto_shadow_manual_override_active"],
            "auto_execution_gate_blockers": list(result["auto_shadow_blockers"]),
            "auto_execution_gate_warnings": list(result["auto_shadow_warnings"]),
        })
        return result
