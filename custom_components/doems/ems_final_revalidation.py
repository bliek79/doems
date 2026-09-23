"""Step 12.3 final live revalidation for automatic Plan72 actions.

Pure/read-only evaluator. It never calls Home Assistant services and never grants
physical execution authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_EXTERNAL_MODE = "third_party_control"


def _number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class DOEMSFinalRevalidation:
    """Perform the last non-actuating validation before mode-switch preview."""

    def evaluate(self, data: dict[str, Any]) -> dict[str, Any]:
        slot = data.get("auto_execution_handoff_selected_slot")
        slots = data.get("scheduler_slots", {}) or {}
        detail = slots.get(slot) or slots.get(str(slot)) or {}
        origin = str(detail.get("origin") or "manual")
        checked_at = datetime.now(timezone.utc)

        base = {
            "auto_final_revalidation_enabled": True,
            "auto_final_revalidation_required": False,
            "auto_final_revalidation_safe": False,
            "auto_final_revalidation_status": "not_required",
            "auto_final_revalidation_reason": "Geen gereed automatic execution handoff",
            "auto_final_revalidation_reasons": [],
            "auto_final_revalidation_warnings": [],
            "auto_final_revalidation_checks": [],
            "auto_final_revalidation_selected_slot": None,
            "auto_final_revalidation_planner_identity": None,
            "auto_final_revalidation_planner_signature": None,
            "auto_final_revalidation_checked_at": checked_at.isoformat(),
            "auto_final_revalidation_action": None,
            "auto_final_revalidation_power_w": None,
            "auto_final_revalidation_target_soc": None,
            "auto_final_revalidation_current_soc": _number(data.get("soc")),
            "auto_final_revalidation_execution_reserve_soc": data.get("auto_prestart_execution_reserve_soc"),
            "auto_final_revalidation_control_path_configured": bool(data.get("control_path_configured")),
            "auto_final_revalidation_controller_idle": not bool(data.get("execution_active")),
            "auto_final_revalidation_physical_test_idle": not bool(data.get("physical_test_active")),
            "auto_final_revalidation_mode_switch_required": data.get("operating_mode") != _EXTERNAL_MODE,
            "auto_final_revalidation_execution_permitted": False,
            "auto_final_revalidation_physical_control": False,
            "service_calls_performed": False,
            "physical_execution_authority": False,
        }

        if (
            slot is None
            or data.get("auto_execution_handoff_required") is not True
            or data.get("auto_execution_handoff_ready") is not True
            or origin != "automatic_72h_planner"
        ):
            return base

        reasons: list[str] = []
        warnings: list[str] = []
        checks: list[dict[str, Any]] = []

        def check(name: str, passed: bool, detail_text: str, blocker: str | None = None, *, warning: str | None = None) -> None:
            severity = "ok" if passed else ("warning" if warning else "blocker")
            checks.append({"check": name, "passed": bool(passed), "severity": severity, "detail": detail_text})
            if not passed:
                if warning:
                    warnings.append(warning)
                elif blocker:
                    reasons.append(blocker)

        action = detail.get("action")
        power_w = _number(detail.get("power_w"))
        target_soc = _number(detail.get("target_soc"))
        runtime_h = _number(detail.get("max_runtime_h"))
        soc = _number(data.get("soc"))
        planner_identity = detail.get("planner_identity")
        planner_signature = detail.get("planner_signature")
        reserve_soc = _number(data.get("auto_prestart_execution_reserve_soc"))
        charge_power = _number(data.get("charge_power_w"))
        discharge_power = _number(data.get("discharge_power_w"))
        min_soc = _number(data.get("technical_min_soc_percent"))
        max_soc = _number(data.get("max_soc_percent"))
        min_soc = 5.0 if min_soc is None else min_soc
        max_soc = 100.0 if max_soc is None else max_soc

        check("execution_handoff_ready", data.get("auto_execution_handoff_ready") is True, "Execution handoff remains ready", "handoff_not_ready")
        check("selected_slot_match", data.get("scheduler_selected_slot") == slot, f"Scheduler selected slot {data.get('scheduler_selected_slot')}; expected {slot}", "scheduler_selection_changed")
        check("automatic_origin", origin == "automatic_72h_planner", f"Origin: {origin}", "invalid_origin")
        check("lifecycle_pending", str(detail.get("lifecycle_status") or "").lower() == "pending", f"Lifecycle: {detail.get('lifecycle_status')}", "plan_not_pending")
        check("scheduler_ready", data.get("scheduler_ready") is True, "Scheduler remains start-ready", "scheduler_not_ready")
        check("prestart_required", data.get("auto_prestart_required") is True, "Authoritative prestart required", "prestart_not_required")
        check("prestart_safe", data.get("auto_prestart_safe") is True, "Authoritative prestart safe", "prestart_not_safe")
        check("safety_handoff_safe", data.get("auto_safety_handoff_safe") is True, "Safety handoff safe", "safety_not_safe")
        check("planner_valid", data.get("auto_plan_72h_valid") is True, "Plan72 valid", "planner_invalid")
        check("forecast_ready", data.get("forecast_ready") is True, "Forecast ready", "forecast_not_ready")
        check("planner_identity_present", bool(planner_identity), "Planner identity present", "planner_identity_missing")
        identity_match = bool(
            planner_identity
            and data.get("auto_prestart_current_identity_match") is True
            and planner_identity == data.get("auto_execution_handoff_planner_identity")
        )
        check("planner_identity_match", identity_match, "Stored identity matches current planner action", "planner_identity_mismatch")
        check("planner_signature_match", data.get("auto_prestart_current_signature_match") is True, "Planner revision unchanged", warning="planner_revision_changed")

        start = _aware(detail.get("start_time"))
        delay_min = _number(detail.get("max_start_delay_min"))
        delay_min = 0.0 if delay_min is None else max(0.0, delay_min)
        within_window = bool(start is not None and start <= checked_at <= start.replace() + __import__("datetime").timedelta(minutes=delay_min))
        check("start_window_valid", within_window, f"Start={detail.get('start_time')}; delay={delay_min} min", "start_window_invalid")

        check("action_valid", action in {"laden", "ontladen"}, f"Action: {action}", "invalid_action")
        max_power = int(data.get("max_discharge_power_w") or 800) if action == "ontladen" else int(data.get("max_charge_power_w") or 800)
        check("power_valid", power_w is not None and 100 <= power_w <= max_power, f"Power={power_w}; allowed=100-{max_power} W", "invalid_power")
        check("runtime_valid", runtime_h is not None and 0.25 <= runtime_h <= 12, f"Runtime={runtime_h} h", "invalid_runtime")
        check("soc_valid", soc is not None and min_soc <= soc <= max_soc, f"SOC={soc}%; allowed={min_soc}-{max_soc}%", "invalid_soc")
        check("target_soc_valid", target_soc is not None and min_soc <= target_soc <= max_soc, f"Target SOC={target_soc}%", "invalid_target_soc")

        direction_ok = bool(
            soc is not None and target_soc is not None and (
                (action == "laden" and soc < target_soc)
                or (action == "ontladen" and soc > target_soc)
            )
        )
        check("target_direction_valid", direction_ok, "Current SOC still requires planned action", "target_already_reached")

        reserve_ok = True
        if action == "ontladen":
            reserve_ok = bool(soc is not None and reserve_soc is not None and soc > reserve_soc)
        check("execution_reserve_available", reserve_ok, f"Execution reserve={reserve_soc}%", "execution_reserve_not_available")

        purpose = str(detail.get("purpose") or "")
        recovery = action == "laden" and purpose in {"veiligheidsladen", "veiligheidsladen+handelsladen"}
        buffer_safe = data.get("auto_plan_72h_execution_buffer_safe") is True
        check("execution_buffer_safe", buffer_safe or recovery, "Execution buffer safe or safety-recovery charge", "execution_buffer_unsafe")

        check("control_path_configured", bool(data.get("control_path_configured")), "Control path configured", "control_path_not_configured")
        check("control_path_pre_mode_ready", data.get("control_path_pre_mode_ready") is True, "Pre-mode control path ready", "control_path_pre_mode_not_ready")
        mode_available = data.get("control_path_operating_mode_available")
        if mode_available is None:
            mode_available = data.get("operating_mode") not in (None, "unknown", "unavailable")
        check("operating_mode_available", bool(mode_available), f"Operating mode={data.get('operating_mode')}", "operating_mode_unavailable")
        check("physical_test_idle", not bool(data.get("physical_test_active")), "Physical test idle", "physical_test_active")
        check("execution_controller_idle", not bool(data.get("execution_active")), "Execution controller idle", "execution_already_active")

        conflicting = bool(
            charge_power is not None and discharge_power is not None
            and charge_power > 100 and discharge_power > 100
        )
        check("no_conflicting_battery_power", not conflicting, f"charge={charge_power} W; discharge={discharge_power} W", "conflicting_battery_power")

        if data.get("operating_mode") != _EXTERNAL_MODE:
            warnings.append("external_mode_switch_required")
            checks.append({
                "check": "external_mode_ready",
                "passed": False,
                "severity": "warning",
                "detail": "Battery is not yet in third_party_control; Step 12.3 only previews the transition",
            })

        reasons = list(dict.fromkeys(reasons))
        warnings = list(dict.fromkeys(warnings))
        safe = not reasons
        return {
            **base,
            "auto_final_revalidation_required": True,
            "auto_final_revalidation_safe": safe,
            "auto_final_revalidation_status": "ready" if safe else "blocked",
            "auto_final_revalidation_reason": (
                "Finale live revalidatie akkoord; mode-switch blijft preview-only"
                if safe else ", ".join(reasons)
            ),
            "auto_final_revalidation_reasons": reasons,
            "auto_final_revalidation_warnings": warnings,
            "auto_final_revalidation_checks": checks,
            "auto_final_revalidation_selected_slot": slot,
            "auto_final_revalidation_planner_identity": planner_identity,
            "auto_final_revalidation_planner_signature": planner_signature,
            "auto_final_revalidation_checked_at": checked_at.isoformat(),
            "auto_final_revalidation_action": action,
            "auto_final_revalidation_power_w": int(power_w) if power_w is not None else None,
            "auto_final_revalidation_target_soc": target_soc,
            "auto_final_revalidation_current_soc": soc,
            "auto_final_revalidation_execution_reserve_soc": reserve_soc,
            "auto_final_revalidation_control_path_configured": bool(data.get("control_path_configured")),
            "auto_final_revalidation_controller_idle": not bool(data.get("execution_active")),
            "auto_final_revalidation_physical_test_idle": not bool(data.get("physical_test_active")),
            "auto_final_revalidation_mode_switch_required": data.get("operating_mode") != _EXTERNAL_MODE,
            "auto_final_revalidation_execution_permitted": False,
            "auto_final_revalidation_physical_control": False,
            "service_calls_performed": False,
            "physical_execution_authority": False,
        }
