"""R8-A: read-only assessment of an already selected R7 plan.

No Home Assistant imports, no storage, no plan selection, no device commands.
R7 remains the sole authority for scheduling and lifecycle.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping


def _aware(value: Any) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo and parsed.utcoffset() is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if isfinite(parsed) else None
    except (TypeError, ValueError, OverflowError):
        return None


def validate_execution_readiness(
    *, plan: Mapping[str, Any], r7: Mapping[str, Any],
    checked_at: datetime, snapshot_identity: str,
    controller_conflict: bool | None = None,
    final_revalidation_safe: bool | None = None,
    handoff_ready: bool | None = None,
) -> dict[str, Any]:
    """Validate evidence only. Never mutate inputs or authorize execution.

    R7 has no execution handoff/final revalidation authority yet. Unless
    independent evidence is explicitly supplied, those gates are unknown.
    """
    missing: list[str] = []
    blockers: list[str] = []
    now = _aware(checked_at)
    if now is None:
        missing.append("aware_checked_at")
    if not snapshot_identity:
        missing.append("snapshot_identity")
    slot = plan.get("slot")
    if type(slot) is not int or slot not in (1, 2, 3):
        blockers.append("invalid_slot")
    if r7.get("selected_slot") != slot:
        blockers.append("r7_selection_mismatch")
    if r7.get("selected_action") != plan.get("action"):
        blockers.append("r7_action_mismatch")
    if r7.get("selected_origin") != plan.get("origin", "manual"):
        blockers.append("r7_origin_mismatch")
    if r7.get("selected_lifecycle") != plan.get("lifecycle_status"):
        blockers.append("r7_lifecycle_mismatch")
    if plan.get("lifecycle_status") != "pending":
        blockers.append("plan_not_pending")
    if plan.get("action") not in ("laden", "ontladen"):
        blockers.append("invalid_action")
    origin = plan.get("origin", "manual")
    identity = plan.get("planner_identity") if origin == "automatic_72h_planner" else plan.get("lifecycle_updated_at")
    if not identity:
        missing.append("plan_identity")
    if origin == "automatic_72h_planner":
        if r7.get("selected_planner_identity") != identity:
            blockers.append("automatic_identity_mismatch")
    elif origin != "manual":
        blockers.append("unknown_origin")
    if not plan.get("lifecycle_updated_at"):
        missing.append("plan_revision")
    if r7.get("physical_execution_enabled") is not False or r7.get("execution_authority") is not False:
        blockers.append("r7_execution_authority_changed")
    if r7.get("safety_status") != "safe" or r7.get("safety_blockers"):
        blockers.append("r7_safety_not_safe")
    # R7 prestart is only applicable to an automatic concept, not pending.
    # A 'not_required' result is NOT proof of a completed prestart check.
    if r7.get("prestart_status") not in ("safe", "not_required"):
        blockers.append("r7_prestart_blocked")
    if final_revalidation_safe is None:
        missing.append("final_revalidation_evidence")
    elif final_revalidation_safe is not True:
        blockers.append("final_revalidation_unsafe")
    if handoff_ready is None:
        missing.append("handoff_evidence")
    elif handoff_ready is not True:
        blockers.append("handoff_not_ready")
    if controller_conflict is None:
        missing.append("controller_conflict_evidence")
    elif controller_conflict is True:
        blockers.append("controller_conflict")
    if plan.get("execution_mode") == "direct" and origin == "manual":
        pass
    elif plan.get("execution_mode") == "gepland":
        start = _aware(plan.get("start_time"))
        delay = _finite(plan.get("max_start_delay_min"))
        if start is None or delay is None or not 1 <= delay <= 120:
            missing.append("valid_start_window")
        elif now is not None and not start <= now <= start + timedelta(minutes=delay):
            blockers.append("outside_start_window")
    else:
        blockers.append("execution_mode_invalid")
    power, target, runtime = (_finite(plan.get(key)) for key in ("power_w", "target_soc", "max_runtime_h"))
    if power is None or target is None or runtime is None:
        missing.append("plan_parameters")
    elif not (100 <= power <= 3500 and 5 <= target <= 100 and 0.25 <= runtime <= 12):
        blockers.append("plan_parameters_invalid")
    # R7 has no revision value in its published selection result: do not
    # manufacture proof that a plan revision was atomically matched.
    missing.append("atomic_plan_revision_evidence")
    status = "not_validated" if missing else ("not_ready" if blockers else "ready")
    return {
        "validation_status": status,
        "technical_ready": status == "ready",
        "execution_authorized": False,
        "execution_performed": False,
        "blockers": tuple(dict.fromkeys(blockers)),
        "missing_evidence": tuple(dict.fromkeys(missing)),
        "snapshot_identity": snapshot_identity,
        "selected_plan_identity": identity,
        "checked_at": now.isoformat() if now is not None else None,
    }
