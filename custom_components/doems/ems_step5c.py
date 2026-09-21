"""Step 5C disarmed physical-authority transfer foundation.

This module is deliberately non-actuating.  It observes the legacy controller
and publishes the single-writer transfer contract while DOEMS remains fully
disarmed.  Live ownership transfer belongs to later acceptance gates.
"""
from __future__ import annotations

from typing import Any

NEUTRAL_POWER_TOLERANCE_W = 25.0


def build_step5c_disarmed_foundation(
    data: dict[str, Any],
    *,
    legacy_automatic_state: str | None,
    legacy_authority_state: str | None,
    legacy_authority_attributes: dict[str, Any] | None,
) -> dict[str, Any]:
    attrs = legacy_authority_attributes or {}
    automatic_known = legacy_automatic_state in {"on", "off"}
    automatic_enabled = legacy_automatic_state == "on"
    legacy_manual_mode = legacy_automatic_state == "off"

    fence = str(
        attrs.get("write_fence")
        or attrs.get("legacy_write_fence")
        or legacy_authority_state
        or "unknown"
    ).lower()
    if fence not in {"open", "closing", "closed"}:
        fence = "unknown"

    try:
        inflight = max(
            0,
            int(
                attrs.get("inflight_calls")
                if attrs.get("inflight_calls") is not None
                else attrs.get("legacy_inflight_calls", 0)
            ),
        )
    except (TypeError, ValueError):
        inflight = 0

    try:
        generation = int(
            attrs.get("authority_generation")
            if attrs.get("authority_generation") is not None
            else attrs.get("legacy_authority_generation", 0)
        )
    except (TypeError, ValueError):
        generation = 0

    charge = data.get("charge_power_w")
    discharge = data.get("discharge_power_w")
    setpoint = data.get("power_setpoint_w")
    mode = data.get("operating_mode")

    measured_zero = (
        charge is not None
        and discharge is not None
        and float(charge) <= NEUTRAL_POWER_TOLERANCE_W
        and float(discharge) <= NEUTRAL_POWER_TOLERANCE_W
    )
    setpoint_zero = setpoint is None or abs(float(setpoint)) <= 0.5
    zero_power_observed = bool(measured_zero and setpoint_zero)
    safe_mode_observed = mode == "self_consumption"
    safe_return_observed = bool(zero_power_observed and safe_mode_observed)

    legacy_quiesced = bool(
        legacy_manual_mode and fence == "closed" and inflight == 0
    )

    blockers: list[str] = ["step5c_live_transfer_disabled"]
    warnings: list[str] = []
    if not automatic_known:
        blockers.append("legacy_automatic_execution_unknown")
    elif automatic_enabled:
        blockers.append("legacy_automatic_execution_on")
    if fence == "unknown":
        blockers.append("legacy_write_fence_unknown")
    elif fence == "open":
        blockers.append("legacy_write_fence_open")
    elif fence == "closing":
        blockers.append("legacy_write_fence_closing")
    if inflight:
        blockers.append("legacy_call_inflight")
    if not zero_power_observed:
        warnings.append("battery_not_zero_power_observed")
    if not safe_mode_observed:
        warnings.append("safe_return_not_observed")

    legacy_observation_ready = automatic_known and fence != "unknown"
    status = (
        "legacy_active_disarmed"
        if legacy_observation_ready
        else "waiting_for_legacy_authority_observation"
    )

    return {
        "step5c_status": status,
        "step5c_phase": "ACTIVE_LEGACY",
        "step5c_implementation_mode": "disarmed_foundation",
        "step5c_live_transfer_enabled": False,
        "step5c_arm_available": False,
        "step5c_service_calls_performed": False,
        "authority_owner": "anker_ems",
        "authority_generation": generation,
        "authority_transition_id": None,
        "legacy_automatic_execution_state": legacy_automatic_state,
        "legacy_automatic_execution_enabled": automatic_enabled,
        "legacy_manual_mode": legacy_manual_mode,
        "legacy_write_fence": fence,
        "legacy_inflight_calls": inflight,
        "legacy_quiesced": legacy_quiesced,
        "legacy_manual_write_blocked": fence == "closed",
        "doems_write_fence": "closed",
        "automatic_execution_armed": False,
        "physical_execution_authority": False,
        "zero_power_verified": False,
        "zero_power_observed": zero_power_observed,
        "safe_return_verified": False,
        "safe_return_observed": safe_return_observed,
        "safe_mode_observed": safe_mode_observed,
        "neutral_stable_seconds": 0,
        "cutover_blockers": blockers,
        "rollback_blockers": [],
        "step5c_warnings": warnings,
        "step5c_abort_reason": None,
        "step5c_last_transition_result": None,
        "last_physical_write_controller": "anker_ems",
        "legacy_write_count": attrs.get("write_count", attrs.get("legacy_write_count")),
        "legacy_blocked_write_count": attrs.get(
            "blocked_write_count", attrs.get("legacy_blocked_write_count")
        ),
        "legacy_last_write_type": attrs.get(
            "last_write_type", attrs.get("legacy_last_write_type")
        ),
        "legacy_last_write_at": attrs.get(
            "last_write_at", attrs.get("legacy_last_write_at")
        ),
        "legacy_observation_ready": legacy_observation_ready,
    }
