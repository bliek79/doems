"""R8-A: non-actuating validation of an existing R7 handoff.

This module does not issue device commands, advance lifecycle states, or
claim execution. It only reports whether a current R7 snapshot is eligible
for a later, separately authorized physical execution implementation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def validate_execution_readiness(
    plan: dict[str, Any],
    scheduler: dict[str, Any],
    *,
    slot: int,
    now: datetime,
    physical_execution_enabled: bool,
    other_controller_active: bool,
) -> dict[str, Any]:
    """Fail closed; return evidence and blockers without side effects."""
    blockers: list[str] = []
    if now.tzinfo is None:
        blockers.append("clock_timezone_missing")
    if slot not in (1, 2, 3) or plan.get("slot", slot) != slot:
        blockers.append("slot_mismatch")
    if plan.get("action") not in ("laden", "ontladen"):
        blockers.append("action_invalid")
    if plan.get("lifecycle_status") != "pending":
        blockers.append("plan_not_pending")
    if scheduler.get("scheduler_selected_slot") != slot:
        blockers.append("scheduler_selection_mismatch")
    if scheduler.get("scheduler_ready") is not True:
        blockers.append("scheduler_not_ready")
    if scheduler.get("safety_ready") is not True:
        blockers.append("safety_not_ready")
    if scheduler.get("prestart_ready") is not True:
        blockers.append("prestart_not_ready")
    if other_controller_active:
        blockers.append("other_controller_active")
    if not physical_execution_enabled:
        blockers.append("physical_execution_disabled")

    start_raw = plan.get("start_time")
    delay = plan.get("max_start_delay_min")
    try:
        start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        if start.tzinfo is None:
            raise ValueError("naive start")
        delay_minutes = float(delay)
        if not 1 <= delay_minutes <= 120:
            raise ValueError("invalid delay")
        if now.tzinfo is not None and not (start <= now <= start + timedelta(minutes=delay_minutes)):
            blockers.append("outside_start_window")
    except (TypeError, ValueError, OverflowError):
        blockers.append("start_window_invalid")

    try:
        power = float(plan.get("power_w"))
        runtime = float(plan.get("max_runtime_h"))
        target = float(plan.get("target_soc"))
        if not (100 <= power <= 3500 and 0.25 <= runtime <= 12 and 5 <= target <= 100):
            blockers.append("plan_parameters_invalid")
    except (TypeError, ValueError):
        blockers.append("plan_parameters_invalid")

    identity = plan.get("planner_identity") if plan.get("origin") == "automatic_72h_planner" else plan.get("lifecycle_updated_at")
    if not identity:
        blockers.append("plan_identity_missing")
    if scheduler.get("plan_identity") is not None and scheduler["plan_identity"] != identity:
        blockers.append("plan_identity_changed")

    return {
        "slot": slot,
        "ready": not blockers,
        "blockers": blockers,
        "checked_at": now.astimezone(timezone.utc).isoformat() if now.tzinfo else None,
        "plan_identity": identity,
        "execution_performed": False,
    }
