"""Step 5B disarmed execution authority preparation.

Builds an immutable execution envelope and a non-actuating transaction rehearsal.
This module has no Home Assistant service-call capability and cannot arm execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

TRADE_PURPOSES = {
    "handelsladen",
    "veiligheidsladen+handelsladen",
    "handel_ontladen",
}

REHEARSAL_PHASES = (
    "PRECHECK",
    "ZERO_POWER_INTENT",
    "MODE_SWITCH_INTENT",
    "WAIT_POST_MODE_INTENT",
    "POST_MODE_REVALIDATION",
    "DIRECTION_INTENT",
    "POWER_INTENT",
    "MONITOR_INTENT",
    "SAFE_RETURN_INTENT",
    "COMPLETE_DISARMED",
)


@dataclass(frozen=True)
class ExecutionEnvelope:
    slot: int
    planner_identity: str
    planner_signature: str
    action: str
    purpose: str
    start_time: str
    planned_end_time: str | None
    power_w: int
    target_soc: float
    max_runtime_h: float
    planned_energy_kwh: float | None
    price_sources: tuple[str, ...]
    all_prices_known: bool
    captured_soc: float
    captured_operating_mode: str | None
    captured_reserve_soc: float | None

    def payload(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "planner_identity": self.planner_identity,
            "planner_signature": self.planner_signature,
            "action": self.action,
            "purpose": self.purpose,
            "start_time": self.start_time,
            "planned_end_time": self.planned_end_time,
            "power_w": self.power_w,
            "target_soc": self.target_soc,
            "max_runtime_h": self.max_runtime_h,
            "planned_energy_kwh": self.planned_energy_kwh,
            "price_sources": list(self.price_sources),
            "all_prices_known": self.all_prices_known,
            "captured_soc": self.captured_soc,
            "captured_operating_mode": self.captured_operating_mode,
            "captured_reserve_soc": self.captured_reserve_soc,
        }

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


def _number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _selected_detail(data: dict[str, Any]) -> tuple[int | None, dict[str, Any]]:
    slot = data.get("scheduler_selected_slot")
    slots = data.get("scheduler_slots", {}) or {}
    detail = slots.get(slot) or slots.get(str(slot)) or {}
    return (slot if isinstance(slot, int) else None), detail


def build_execution_envelope(data: dict[str, Any]) -> tuple[ExecutionEnvelope | None, list[str], list[str]]:
    """Capture an immutable envelope only from a fully green Step 5A state."""
    blockers: list[str] = []
    warnings: list[str] = []

    slot, detail = _selected_detail(data)
    if data.get("auto_shadow_status") != "ready_disarmed":
        blockers.append("step5a_not_ready_disarmed")
    if data.get("auto_shadow_technical_ready") is not True:
        blockers.append("step5a_not_technical_ready")
    if data.get("auto_shadow_armed") is not False:
        blockers.append("automatic_execution_armed_must_remain_false")
    if data.get("auto_shadow_execution_permitted") is not False:
        blockers.append("execution_permission_must_remain_false")
    if slot is None or data.get("scheduler_ready") is not True:
        blockers.append("no_start_ready_automatic_action")
    if str(detail.get("origin") or "") != "automatic_72h_planner":
        blockers.append("selected_plan_not_automatic")
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
    if data.get("control_path_configured") is not True:
        blockers.append("control_path_not_configured")
    if data.get("auto_shadow_control_path_ready") is not True:
        blockers.append("control_path_not_ready")
    if data.get("physical_test_active"):
        blockers.append("physical_test_active")
    if data.get("execution_active"):
        blockers.append("execution_active")
    if data.get("auto_shadow_manual_override_active"):
        blockers.append("manual_override_active")
    if data.get("forecast_ready") is not True:
        blockers.append("forecast_not_ready")

    identity = detail.get("planner_identity")
    signature = detail.get("planner_signature")
    if not identity:
        blockers.append("planner_identity_missing")
    if not signature:
        blockers.append("planner_signature_missing")

    action = str(detail.get("action") or "")
    purpose = str(detail.get("purpose") or "")
    if action not in {"laden", "ontladen"}:
        blockers.append("invalid_action")
    if not purpose:
        blockers.append("purpose_missing")

    power_w = _number(detail.get("power_w"))
    target_soc = _number(detail.get("target_soc"))
    runtime_h = _number(detail.get("max_runtime_h"))
    current_soc = _number(data.get("soc"))
    reserve_soc = _number(detail.get("execution_reserve_start_soc"))

    max_power = (
        _number(data.get("max_discharge_power_w"))
        if action == "ontladen"
        else _number(data.get("max_charge_power_w"))
    )
    if power_w is None or max_power is None or not 100 <= power_w <= max_power:
        blockers.append("invalid_power")
    if target_soc is None or not 5 <= target_soc <= 100:
        blockers.append("invalid_target_soc")
    if runtime_h is None or not 0.25 <= runtime_h <= 12:
        blockers.append("invalid_runtime")
    if current_soc is None or not 5 <= current_soc <= 100:
        blockers.append("invalid_soc")
    elif target_soc is not None:
        if action == "laden" and current_soc >= target_soc:
            blockers.append("charge_target_already_reached")
        if action == "ontladen" and current_soc <= target_soc:
            blockers.append("discharge_target_already_reached")

    start_time = detail.get("start_time")
    if not start_time:
        blockers.append("start_time_missing")
    if purpose in TRADE_PURPOSES and not bool(detail.get("all_prices_known")):
        blockers.append("trade_requires_known_prices")
    elif not bool(detail.get("all_prices_known")):
        warnings.append("forecast_price_used_for_non_trade_planning")

    if blockers:
        return None, list(dict.fromkeys(blockers)), list(dict.fromkeys(warnings))

    envelope = ExecutionEnvelope(
        slot=int(slot),
        planner_identity=str(identity),
        planner_signature=str(signature),
        action=action,
        purpose=purpose,
        start_time=str(start_time),
        planned_end_time=(
            str(detail.get("planned_end_time"))
            if detail.get("planned_end_time")
            else None
        ),
        power_w=int(round(float(power_w))),
        target_soc=float(target_soc),
        max_runtime_h=float(runtime_h),
        planned_energy_kwh=_number(detail.get("planned_energy_kwh")),
        price_sources=tuple(str(v) for v in (detail.get("price_sources") or [])),
        all_prices_known=bool(detail.get("all_prices_known")),
        captured_soc=float(current_soc),
        captured_operating_mode=(
            str(data.get("operating_mode")) if data.get("operating_mode") else None
        ),
        captured_reserve_soc=reserve_soc,
    )
    return envelope, [], list(dict.fromkeys(warnings))


def validate_envelope_unchanged(
    data: dict[str, Any],
    envelope: ExecutionEnvelope,
) -> tuple[bool, list[str]]:
    """Fail closed if the captured action changed after envelope creation."""
    blockers: list[str] = []
    slot, detail = _selected_detail(data)
    if slot != envelope.slot:
        blockers.append("selected_slot_changed")
    if detail.get("planner_identity") != envelope.planner_identity:
        blockers.append("planner_identity_changed")
    if detail.get("planner_signature") != envelope.planner_signature:
        blockers.append("planner_signature_changed_after_capture")
    if detail.get("action") != envelope.action:
        blockers.append("action_changed")
    if str(detail.get("purpose") or "") != envelope.purpose:
        blockers.append("purpose_changed")
    if str(detail.get("start_time") or "") != envelope.start_time:
        blockers.append("start_time_changed")
    if str(detail.get("planned_end_time") or "") != str(envelope.planned_end_time or ""):
        blockers.append("planned_end_time_changed")
    if _number(detail.get("power_w")) != float(envelope.power_w):
        blockers.append("power_changed")
    if _number(detail.get("target_soc")) != float(envelope.target_soc):
        blockers.append("target_soc_changed")
    if _number(detail.get("max_runtime_h")) != float(envelope.max_runtime_h):
        blockers.append("runtime_changed")
    return (not blockers), list(dict.fromkeys(blockers))


def build_step5b_rehearsal(
    data: dict[str, Any],
    *,
    previous_envelope: ExecutionEnvelope | None = None,
) -> dict[str, Any]:
    """Build a complete non-actuating Step 5B transaction rehearsal."""
    blockers: list[str] = []
    warnings: list[str] = []
    envelope = previous_envelope

    if envelope is None:
        envelope, blockers, warnings = build_execution_envelope(data)
        if envelope is None:
            return {
                "step5b_status": "blocked_disarmed",
                "step5b_envelope_ready": False,
                "step5b_envelope": None,
                "step5b_envelope_fingerprint": None,
                "step5b_transaction_phase": "PRECHECK",
                "step5b_transaction_ready": False,
                "step5b_rehearsal_phases": list(REHEARSAL_PHASES),
                "step5b_blockers": blockers,
                "step5b_warnings": warnings,
                "step5b_abort_reason": blockers[0] if blockers else None,
                "step5b_authority_fence": False,
                "step5b_service_calls_performed": False,
                "automatic_execution_armed": False,
                "physical_execution_authority": False,
            }
    else:
        unchanged, change_blockers = validate_envelope_unchanged(data, envelope)
        if not unchanged:
            blockers.extend(change_blockers)

    if data.get("auto_shadow_status") != "ready_disarmed":
        blockers.append("step5a_no_longer_ready_disarmed")
    if data.get("auto_shadow_technical_ready") is not True:
        blockers.append("step5a_no_longer_technical_ready")
    if data.get("auto_shadow_armed") is not False:
        blockers.append("automatic_execution_armed_must_remain_false")
    if data.get("auto_shadow_execution_permitted") is not False:
        blockers.append("execution_permission_must_remain_false")

    current_soc = _number(data.get("soc"))
    if current_soc is None:
        blockers.append("soc_unavailable")
    else:
        if envelope.action == "laden" and current_soc >= envelope.target_soc:
            blockers.append("charge_target_already_reached")
        if envelope.action == "ontladen" and current_soc <= envelope.target_soc:
            blockers.append("discharge_target_already_reached")

    if data.get("physical_test_active"):
        blockers.append("physical_test_active")
    if data.get("execution_active"):
        blockers.append("execution_active")
    if data.get("auto_shadow_manual_override_active"):
        blockers.append("manual_override_active")
    if data.get("auto_shadow_control_path_ready") is not True:
        blockers.append("control_path_not_ready")
    if data.get("forecast_ready") is not True:
        blockers.append("forecast_not_ready")

    mode = data.get("operating_mode")
    post_mode_required = mode == "third_party_control"
    if post_mode_required:
        if data.get("control_path_post_mode_ready") is not True:
            blockers.append("post_mode_not_ready")
        direction = data.get("action_direction")
        expected_direction = "charge" if envelope.action == "laden" else "discharge"
        if direction is not None and direction != expected_direction:
            blockers.append("external_direction_conflict")
        setpoint = _number(data.get("power_setpoint_w"))
        if setpoint is not None and setpoint not in {0.0, float(envelope.power_w)}:
            blockers.append("external_power_setpoint_conflict")

    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    if blockers:
        status = "aborted_disarmed" if previous_envelope is not None else "blocked_disarmed"
        phase = "ABORTED_DISARMED" if previous_envelope is not None else "PRECHECK"
        return {
            "step5b_status": status,
            "step5b_envelope_ready": True,
            "step5b_envelope": envelope.payload(),
            "step5b_envelope_fingerprint": envelope.fingerprint,
            "step5b_transaction_phase": phase,
            "step5b_transaction_ready": False,
            "step5b_rehearsal_phases": list(REHEARSAL_PHASES),
            "step5b_blockers": blockers,
            "step5b_warnings": warnings,
            "step5b_abort_reason": blockers[0],
            "step5b_authority_fence": False,
            "step5b_service_calls_performed": False,
            "automatic_execution_armed": False,
            "physical_execution_authority": False,
        }

    return {
        "step5b_status": "prepared_disarmed",
        "step5b_envelope_ready": True,
        "step5b_envelope": envelope.payload(),
        "step5b_envelope_fingerprint": envelope.fingerprint,
        "step5b_transaction_phase": "COMPLETE_DISARMED",
        "step5b_transaction_ready": True,
        "step5b_rehearsal_phases": list(REHEARSAL_PHASES),
        "step5b_blockers": [],
        "step5b_warnings": warnings,
        "step5b_abort_reason": None,
        "step5b_authority_fence": False,
        "step5b_service_calls_performed": False,
        "automatic_execution_armed": False,
        "physical_execution_authority": False,
    }
