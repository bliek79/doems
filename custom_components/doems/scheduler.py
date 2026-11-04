"""Read-only three-slot selection following Anker EMS Alpha84.

No energy projection, storage mutation or execution permission lives here.
The two deliberate input adaptations are strict timezone-aware timestamps and
zero start delay for chapter-7 automatic plans. Selection order is unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

AUTOMATIC = "automatic_72h_planner"
AUTHORITY = {"observational_only": True, "physical_execution_authority": False,
             "execution_enabled": False, "scheduler_physical_control": False}


def timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        return stamp.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value: Any, minimum: float, maximum: float) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and minimum <= value <= maximum and isfinite(value))


def _invalid(plan: dict, charge_limit: Any, discharge_limit: Any) -> str | None:
    if plan.get("lifecycle_status") != "pending":
        return "invalid_lifecycle"
    action = plan.get("action")
    if action not in ("laden", "ontladen"):
        return "invalid_action"
    if plan.get("execution_mode") not in ("direct", "gepland"):
        return "invalid_execution_mode"
    if plan.get("origin", "manual") not in ("manual", AUTOMATIC):
        return "invalid_origin"
    limit = charge_limit if action == "laden" else discharge_limit
    if not _number(limit, 100, 3500):
        return "invalid_power_limit"
    if not _number(plan.get("power_w"), 100, limit):
        return "invalid_power"
    if not _number(plan.get("target_soc"), 5, 100):
        return "invalid_target_soc"
    if not _number(plan.get("max_runtime_h"), .25, 12):
        return "invalid_runtime"
    minimum_delay = 0 if plan.get("origin") == AUTOMATIC else 1
    if not _number(plan.get("max_start_delay_min"), minimum_delay, 120):
        return "invalid_start_delay"
    # Retain both meanings; never substitute a projected SOC for a command.
    if plan.get("command_target_soc") is not None and not _number(plan["command_target_soc"], 5, 100):
        return "invalid_command_target_soc"
    if plan.get("projected_end_soc") is not None and not _number(plan["projected_end_soc"], 0, 100):
        return "invalid_projected_end_soc"
    start = timestamp(plan.get("start_time"))
    end = timestamp(plan.get("planned_end_time"))
    power_start = timestamp(plan.get("power_start_time"))
    if plan.get("origin") == AUTOMATIC:
        for field in ("planner_identity", "planner_signature", "source_input_fingerprint", "source_window_id"):
            if not isinstance(plan.get(field), str) or not plan[field]:
                return "missing_" + field
        generation = plan.get("source_plan_generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            return "invalid_source_generation"
        if plan.get("execution_mode") != "gepland":
            return "invalid_automatic_mode"
        if plan.get("command_target_soc") is None or plan.get("projected_end_soc") is None:
            return "missing_automatic_soc_fields"
        if start is None or power_start is None or end is None:
            return "invalid_automatic_times"
    if plan.get("planned_end_time") is not None and (end is None or start is None or end <= start):
        return "invalid_end_time"
    if plan.get("power_start_time") is not None and (
        power_start is None or start is None or end is None or not start <= power_start < end
    ):
        return "invalid_power_start_time"
    return None


def evaluate(plans: dict[int, dict], *, now: datetime, max_charge_power_w: Any,
             max_discharge_power_w: Any, storage_revision: int = 0,
             source_blocker: str | None = None) -> dict:
    """Evaluate one immutable read snapshot; start-window end is inclusive.

    An active slot is excluded but does not suppress selection of another slot,
    exactly as in Alpha84. Exclusive execution belongs to chapters 9--12.
    """
    current = timestamp(now)
    if current is None:
        raise ValueError("timezone_aware_now_required")
    details, candidates, future, transitions = {}, [], [], []
    for slot in range(1, 4):
        plan = deepcopy(plans.get(slot, {}))
        detail = {**plan, "slot": slot, "selected": False, "physical_control": False}
        start = timestamp(plan.get("start_time"))
        end = timestamp(plan.get("planned_end_time"))
        delay = plan.get("max_start_delay_min")
        window_end = None
        if start is not None and _number(delay, 0, 120):
            try:
                window_end = start + timedelta(minutes=delay)
            except OverflowError:
                pass
        detail["start_window_end"] = window_end.isoformat() if window_end else None
        lifecycle = plan.get("lifecycle_status")
        invalid = None
        if lifecycle in ("actief", "voltooid", "geannuleerd", "fout"):
            status, reason = lifecycle, "lifecycle_" + lifecycle
        elif plan.get("action") == "geen":
            status, reason = "leeg", "empty_slot"
        elif lifecycle == "concept":
            status, reason = "concept", "not_scheduled"
        elif (invalid := _invalid(plan, max_charge_power_w, max_discharge_power_w)):
            status, reason = "ongeldig", invalid
        elif end is not None and current >= end:
            status, reason = "verlopen", "planned_end_reached"
        elif plan.get("execution_mode") == "direct":
            status, reason = "kandidaat", "direct_ready"
            candidates.append((1, current, slot))
        elif start is None:
            status, reason = "wacht_op_starttijd", "missing_or_unaware_start_time"
        elif window_end is None:
            status, reason = "ongeldig", "invalid_start_window"
        elif current < start:
            status, reason = "wachtend", "before_start"
            future.append((start, slot))
        elif current <= window_end:
            status, reason = "kandidaat", "scheduled_due"
            candidates.append((0, start, slot))
        else:
            status, reason = "verlopen", "start_window_expired"
        if lifecycle == "pending" and status not in {"ongeldig", "verlopen"}:
            for boundary in (start, end):
                if boundary is not None and boundary > current:
                    transitions.append(boundary)
            if window_end is not None:
                try:
                    expiry = window_end + timedelta(microseconds=1)
                    if expiry > current:
                        transitions.append(expiry)
                except OverflowError:
                    pass
        detail.update(status=status, reason=reason)
        details[slot] = detail

    candidates.sort()  # Alpha84: scheduled first, oldest start, then slot.
    selected = candidates[0][2] if candidates and not source_blocker else None
    for _, _, slot in candidates:
        details[slot].update(
            selected=slot == selected,
            status="startklaar" if slot == selected else "geblokkeerd",
            reason=(source_blocker or ("scheduled_due" if candidates[0][0] == 0 else "direct_ready"))
                   if slot == selected or source_blocker else "another_slot_selected",
        )
    future.sort()
    chosen = details.get(selected, {})
    if source_blocker:
        status, reason = "geblokkeerd", source_blocker
    elif selected is not None:
        status, reason = "startklaar", chosen["reason"]
    elif any(d["status"] == "actief" for d in details.values()):
        status, reason = "actief", "active_slot_present"
    elif future:
        status, reason = "wachtend", "before_start"
    elif any(d["status"] in {"ongeldig", "wacht_op_starttijd", "verlopen"} for d in details.values()):
        status, reason = "aandacht", "no_eligible_slot"
    else:
        status, reason = "idle", "no_pending_action"
    return {
        **AUTHORITY, "scheduler_status": status, "scheduler_reason": reason,
        "scheduler_selected_slot": selected, "scheduler_ready": selected is not None,
        "scheduler_selected_action": chosen.get("action"),
        "scheduler_selected_execution_mode": chosen.get("execution_mode"),
        "scheduler_selected_start_time": chosen.get("start_time") if chosen.get("execution_mode") == "gepland" else None,
        "scheduler_next_future_slot": future[0][1] if future else None,
        "scheduler_next_future_start": future[0][0].isoformat() if future else None,
        "scheduler_slots": details, "storage_revision": storage_revision,
        "evaluated_at": current.isoformat(),
        "next_evaluation_at": min(transitions).isoformat() if transitions else None,
        "active_slots": [i for i, d in details.items() if d["status"] == "actief"],
        "selection_semantics": "candidate_for_later_validation_not_execution_permission",
    }
