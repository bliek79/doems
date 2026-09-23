"""Step 12.4 Automatic Execution Gate.

This module turns the fully validated Step 12.3 shadow chain into a single
fail-safe, non-actuating permission decision. It never calls Home Assistant
services, never starts the Execution Controller and never grants physical
execution authority.
"""
from __future__ import annotations

from typing import Any

_TRADE_PURPOSES = {
    "handelsladen",
    "veiligheidsladen+handelsladen",
    "handel_ontladen",
}
_SAFETY_RECOVERY_PURPOSES = {
    "veiligheidsladen",
    "veiligheidsladen+handelsladen",
}


class DOEMSAutomaticExecutionGate:
    """Evaluate the final technical gate before the later Execution Controller."""

    def evaluate(self, data: dict[str, Any], *, armed: bool) -> dict[str, Any]:
        slot = data.get("scheduler_selected_slot")
        slots = data.get("scheduler_slots", {}) or {}
        detail = slots.get(slot) or slots.get(str(slot)) or {}
        origin = str(detail.get("origin") or "manual")
        purpose = str(detail.get("purpose") or "")
        action = str(detail.get("action") or "")
        planner_identity = detail.get("planner_identity")
        automatic_selected = bool(
            slot is not None
            and data.get("scheduler_ready") is True
            and origin == "automatic_72h_planner"
        )

        blockers: list[str] = []
        warnings: list[str] = []
        checks: list[dict[str, Any]] = []
        manual_override = bool(
            (
                slot is not None
                and data.get("scheduler_ready") is True
                and origin != "automatic_72h_planner"
            )
            or (
                data.get("execution_active")
                and str(data.get("execution_origin") or "manual")
                != "automatic_72h_planner"
            )
        )

        def check(
            name: str,
            passed: bool,
            detail_text: str,
            blocker: str | None = None,
            *,
            warning: str | None = None,
        ) -> None:
            severity = "ok" if passed else ("warning" if warning else "blocker")
            checks.append(
                {
                    "check": name,
                    "passed": bool(passed),
                    "severity": severity,
                    "detail": detail_text,
                }
            )
            if passed:
                return
            if warning:
                warnings.append(warning)
            elif blocker:
                blockers.append(blocker)

        check(
            "automatic_action_selected",
            automatic_selected,
            f"slot={slot}; origin={origin}",
            "no_automatic_action_selected",
        )
        if manual_override:
            check(
                "manual_override_clear",
                False,
                "Manual/legacy execution has priority",
                "manual_override_active",
            )

        if automatic_selected:
            check(
                "prestart_safe",
                data.get("auto_prestart_safe") is True,
                "Authoritative prestart is safe",
                "prestart_not_safe",
            )
            check(
                "safety_handoff_safe",
                data.get("auto_safety_handoff_safe") is True,
                "Safety handoff is safe",
                "safety_handoff_not_safe",
            )
            check(
                "execution_handoff_ready",
                data.get("auto_execution_handoff_ready") is True,
                "Execution handoff is ready",
                "execution_handoff_not_ready",
            )
            check(
                "final_revalidation_safe",
                data.get("auto_final_revalidation_safe") is True,
                "Final revalidation is safe",
                "final_revalidation_not_safe",
            )
            check(
                "mode_switch_preview_ready",
                data.get("auto_mode_switch_preview_ready") is True,
                "Mode-switch preview is ready",
                "mode_switch_preview_not_ready",
            )

            final_slot = data.get("auto_final_revalidation_selected_slot")
            check(
                "selected_slot_stable",
                final_slot == slot,
                f"scheduler_slot={slot}; final_slot={final_slot}",
                "selected_slot_changed",
            )
            final_identity = data.get("auto_final_revalidation_planner_identity")
            check(
                "planner_identity_stable",
                bool(planner_identity)
                and planner_identity == final_identity
                and planner_identity == data.get("auto_execution_handoff_planner_identity"),
                "Planner identity is unchanged across handoff/revalidation/gate",
                "planner_identity_changed",
            )

            signature_match = data.get("auto_prestart_current_signature_match") is True
            check(
                "planner_signature_current",
                signature_match,
                "Planner signature is unchanged",
                warning="planner_revision_changed",
            )

            recovery = bool(
                action == "laden" and purpose in _SAFETY_RECOVERY_PURPOSES
            )
            buffer_safe = data.get("auto_plan_72h_execution_buffer_safe") is True
            check(
                "execution_buffer_safe",
                buffer_safe or recovery,
                (
                    "Execution buffer safe"
                    if buffer_safe
                    else "Unsafe execution buffer accepted only for safety-recovery charging"
                ),
                "execution_buffer_unsafe",
            )

            check(
                "forecast_ready",
                data.get("forecast_ready") is True,
                "Forecast contract is ready",
                "forecast_not_ready",
            )
            check(
                "control_path_configured",
                bool(data.get("control_path_configured")),
                "Control path configured",
                "control_path_not_configured",
            )
            stable_seconds = float(data.get("control_path_stable_seconds") or 0)
            required_stable_seconds = float(
                data.get("control_path_required_stable_seconds") or 60
            )
            check(
                "control_path_stable",
                data.get("control_path_ready") is True
                and stable_seconds >= required_stable_seconds,
                (
                    f"control_path_ready={data.get('control_path_ready')}; "
                    f"stable_s={stable_seconds}; required_s={required_stable_seconds}"
                ),
                "control_path_not_stable",
            )
            check(
                "physical_test_idle",
                not bool(data.get("physical_test_active")),
                "Physical test idle",
                "physical_test_active",
            )
            check(
                "execution_idle",
                not bool(data.get("execution_active")),
                "Execution controller idle",
                "execution_already_active",
            )

            all_prices_known = bool(detail.get("all_prices_known"))
            is_trade = purpose in _TRADE_PURPOSES
            check(
                "price_execution_safe",
                (not is_trade) or all_prices_known,
                (
                    f"purpose={purpose}; all_prices_known={all_prices_known}"
                ),
                "trade_requires_known_prices",
            )
            if not is_trade and not all_prices_known:
                warnings.append("forecast_price_used_for_non_trade_planning")
        else:
            recovery = False
            buffer_safe = data.get("auto_plan_72h_execution_buffer_safe") is True
            all_prices_known = bool(detail.get("all_prices_known"))

        blockers = list(dict.fromkeys(blockers))
        warnings = list(dict.fromkeys(warnings))

        technical_ready = bool(automatic_selected and not blockers)
        execution_permitted = bool(technical_ready and armed)

        if not automatic_selected and not manual_override:
            status = "idle"
        elif not technical_ready:
            status = "blocked"
        elif not armed:
            status = "ready_disarmed"
        else:
            status = "armed_ready"

        return {
            "auto_execution_gate_enabled": True,
            "auto_execution_gate_status": status,
            "auto_execution_gate_technical_ready": technical_ready,
            "auto_execution_gate_armed": bool(armed),
            "auto_execution_gate_execution_permitted": execution_permitted,
            "auto_execution_gate_selected_slot": slot if automatic_selected else None,
            "auto_execution_gate_planner_identity": planner_identity if automatic_selected else None,
            "auto_execution_gate_action": detail.get("action") if automatic_selected else None,
            "auto_execution_gate_purpose": purpose or None,
            "auto_execution_gate_power_w": detail.get("power_w") if automatic_selected else None,
            "auto_execution_gate_target_soc": detail.get("target_soc") if automatic_selected else None,
            "auto_execution_gate_max_runtime_h": detail.get("max_runtime_h") if automatic_selected else None,
            "auto_execution_gate_price_sources": list(detail.get("price_sources") or []),
            "auto_execution_gate_all_prices_known": all_prices_known,
            "auto_execution_gate_safety_recovery_exception": recovery,
            "auto_execution_gate_execution_buffer_safe": buffer_safe,
            "auto_execution_gate_manual_override_active": manual_override,
            "auto_execution_gate_blockers": blockers,
            "auto_execution_gate_warnings": warnings,
            "auto_execution_gate_checks": checks,
            "auto_execution_gate_execution_controller_invoked": False,
            "auto_execution_gate_service_calls_performed": False,
            "auto_execution_gate_physical_execution_authority": False,
            "automatic_execution_armed": bool(armed),
            "execution_controller_invoked": False,
            "service_calls_performed": False,
            "physical_execution_authority": False,
        }
