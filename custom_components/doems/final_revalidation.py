"""Alpha84 final revalidation, ported for standalone DOEMS (automatic slots)."""
from __future__ import annotations
from typing import Any
from homeassistant.util import dt as dt_util

_EXTERNAL_MODE = "third_party_control"

class DOEMSFinalRevalidation:
    @staticmethod
    def _number_value(value):
        try:
            value = float(value)
            return value if value == value and abs(value) != float("inf") else None
        except (TypeError, ValueError, OverflowError):
            return None

    def evaluate_final_revalidation(self, data: dict[str, Any]) -> dict[str, Any]:
        """Perform the last non-actuating live validation before a future mode switch.

        Alpha38 keeps physical execution disabled. This gate mirrors the exact
        conditions that must still be true immediately before the Execution
        Controller may switch the battery to external control in a later
        release. It is intentionally evaluated from the latest coordinator
        snapshot and never calls Home Assistant services.
        """
        slot = data.get("auto_execution_handoff_selected_slot")
        slots = data.get("scheduler_slots", {}) or {}
        detail = slots.get(slot) or slots.get(str(slot)) or {}
        origin = str(detail.get("origin") or "manual")

        base = {
            "auto_final_revalidation_enabled": True,
            "auto_final_revalidation_required": False,
            "auto_final_revalidation_safe": False,
            "auto_final_revalidation_status": "not_required",
            "auto_final_revalidation_reason": "Geen Execution Controller handoff gereed voor finale live validatie",
            "auto_final_revalidation_reasons": [],
            "auto_final_revalidation_warnings": [],
            "auto_final_revalidation_checks": [],
            "auto_final_revalidation_selected_slot": None,
            "auto_final_revalidation_planner_identity": None,
            "auto_final_revalidation_planner_signature": None,
            "auto_final_revalidation_checked_at": dt_util.now().isoformat(),
            "auto_final_revalidation_action": None,
            "auto_final_revalidation_power_w": None,
            "auto_final_revalidation_target_soc": None,
            "auto_final_revalidation_current_soc": self._number_value(data.get("soc")),
            "auto_final_revalidation_execution_reserve_soc": data.get("auto_prestart_execution_reserve_soc"),
            "auto_final_revalidation_control_path_configured": bool(data.get("control_path_configured")),
            "auto_final_revalidation_controller_idle": not bool(data.get("execution_active")),
            "auto_final_revalidation_physical_test_idle": not bool(data.get("physical_test_active")),
            "auto_final_revalidation_mode_switch_required": data.get("operating_mode") != _EXTERNAL_MODE,
            "auto_final_revalidation_execution_permitted": False,
            "auto_final_revalidation_physical_control": False,
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

        def add_check(name: str, passed: bool, detail_text: str, *, warning_only: bool = False) -> None:
            severity = "ok" if passed else ("warning" if warning_only else "blocker")
            checks.append({"check": name, "passed": passed, "severity": severity, "detail": detail_text})
            if not passed:
                (warnings if warning_only else reasons).append(name)

        action = detail.get("action")
        power_w = self._number_value(detail.get("power_w"))
        target_soc = self._number_value(detail.get("target_soc"))
        soc = self._number_value(data.get("soc"))
        charge_power = self._number_value(data.get("charge_power_w"))
        discharge_power = self._number_value(data.get("discharge_power_w"))
        planner_identity = detail.get("planner_identity")
        planner_signature = detail.get("planner_signature")
        reserve_soc = self._number_value(data.get("auto_prestart_execution_reserve_soc"))

        add_check("scheduler_ready", bool(data.get("scheduler_ready")), "Scheduler still has a start-ready plan")
        add_check("selected_slot_match", data.get("scheduler_selected_slot") == slot, f"Selected slot: {data.get('scheduler_selected_slot')}; expected: {slot}")
        add_check("automatic_origin", origin == "automatic_72h_planner", f"Origin: {origin}")
        add_check("prestart_safe", data.get("auto_prestart_safe") is True, "Authoritative pre-start gate safe")
        add_check("safety_handoff_safe", data.get("auto_safety_handoff_safe") is True, "Safety Guard handoff safe")
        add_check("execution_handoff_ready", data.get("auto_execution_handoff_ready") is True, "Execution handoff ready")
        add_check("planner_identity_match", data.get("auto_prestart_current_identity_match") is True and planner_identity == data.get("auto_execution_handoff_planner_identity"), "Planner identity unchanged")
        add_check("planner_signature_match", data.get("auto_prestart_current_signature_match") is True, "Planner revision unchanged", warning_only=True)
        add_check("forecast_ready", data.get("forecast_ready") is True, "Forecast sources ready")
        purpose = str(detail.get("purpose") or "")
        safety_recovery_action = bool(
            action == "laden"
            and purpose in {"veiligheidsladen", "veiligheidsladen+handelsladen"}
        )
        execution_buffer_safe = data.get("auto_plan_72h_execution_buffer_safe") is True
        add_check(
            "execution_buffer_safe",
            execution_buffer_safe or safety_recovery_action,
            (
                "Execution buffer safe"
                if execution_buffer_safe
                else "Execution buffer unsafe; safety charge is allowed to restore it"
            ),
        )
        add_check("control_path_configured", bool(data.get("control_path_configured")), "Control path configured")
        add_check("controller_idle", not bool(data.get("execution_active")), "Execution Controller idle")
        add_check("physical_test_idle", not bool(data.get("physical_test_active")), "Physical test idle")
        add_check("action_valid", action in {"laden", "ontladen"}, f"Action: {action}")

        max_power = int(data.get("max_discharge_power_w") or 800) if action == "ontladen" else int(data.get("max_charge_power_w") or 800)
        add_check("power_valid", power_w is not None and 100 <= power_w <= max_power, f"Power: {power_w} W; allowed 100-{max_power} W")
        add_check("soc_valid", soc is not None and 0 <= soc <= 100, f"Current SOC: {soc}%")
        add_check("target_soc_valid", target_soc is not None and 5 <= target_soc <= 100, f"Target SOC: {target_soc}%")

        direction_ok = False
        if soc is not None and target_soc is not None:
            if action == "laden":
                direction_ok = soc < target_soc
            elif action == "ontladen":
                direction_ok = soc > target_soc
        add_check("target_direction_valid", direction_ok, "Current SOC still requires the planned action")

        reserve_ok = True
        if action == "ontladen":
            reserve_ok = soc is not None and reserve_soc is not None and soc > reserve_soc
        add_check("execution_reserve_available", reserve_ok, f"Execution reserve: {reserve_soc}%")

        conflicting_power = (
            charge_power is not None
            and discharge_power is not None
            and charge_power > 100
            and discharge_power > 100
        )
        add_check("no_conflicting_battery_power", not conflicting_power, f"Charge: {charge_power} W; discharge: {discharge_power} W")

        if data.get("operating_mode") != _EXTERNAL_MODE:
            warnings.append("external_mode_switch_required")
            checks.append({
                "check": "external_mode_ready",
                "passed": False,
                "severity": "warning",
                "detail": "Battery is not yet in third_party_control; the Execution Controller switches mode after this gate when automatic execution is armed",
            })
        else:
            checks.append({
                "check": "external_mode_ready",
                "passed": True,
                "severity": "ok",
                "detail": "Battery already in third_party_control",
            })

        safe = not reasons
        return {
            **base,
            "auto_final_revalidation_required": True,
            "auto_final_revalidation_safe": safe,
            "auto_final_revalidation_status": "ready_observe" if safe else "blocked",
            "auto_final_revalidation_reason": (
                "Finale live revalidatie akkoord; toekomstige mode-switch mag pas in een latere release worden vrijgegeven"
                if safe
                else ", ".join(reasons)
            ),
            "auto_final_revalidation_reasons": reasons,
            "auto_final_revalidation_warnings": warnings,
            "auto_final_revalidation_checks": checks,
            "auto_final_revalidation_selected_slot": slot,
            "auto_final_revalidation_planner_identity": planner_identity,
            "auto_final_revalidation_planner_signature": planner_signature,
            "auto_final_revalidation_checked_at": dt_util.now().isoformat(),
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
        }

