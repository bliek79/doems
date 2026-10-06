"""Pure manual Plan Store semantics for the DOEMS reset line."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping

PLAN_SLOT_COUNT = 3

CONTROL_FIELDS = {
    "action",
    "execution_mode",
    "start_time",
    "power_w",
    "target_soc",
    "max_runtime_h",
    "max_start_delay_min",
}

LIFECYCLE_STATUSES = {
    "concept",
    "pending",
    "actief",
    "voltooid",
    "geannuleerd",
    "fout",
}

TERMINAL_LIFECYCLES = {"voltooid", "geannuleerd", "fout"}

DEFAULT_PLAN: dict[str, Any] = {
    "action": "geen",
    "execution_mode": "direct",
    "start_time": None,
    "power_w": 100.0,
    "target_soc": 80.0,
    "max_runtime_h": 2.0,
    "max_start_delay_min": 15.0,
    "lifecycle_status": "concept",
    "lifecycle_reason": None,
    "lifecycle_updated_at": None,
    "origin": "manual",
}


def new_manual_plan() -> dict[str, Any]:
    """Return a clean independent manual plan slot."""
    return deepcopy(DEFAULT_PLAN)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def validate_manual_plan(
    plan: Mapping[str, Any],
    *,
    now: datetime | None = None,
    require_future_start: bool = False,
) -> list[str]:
    """Return deterministic plan blockers without performing any execution."""
    blockers: list[str] = []
    action = str(plan.get("action") or "geen")
    execution_mode = str(plan.get("execution_mode") or "")

    if action not in {"laden", "ontladen"}:
        blockers.append("action_required")
    if execution_mode not in {"direct", "gepland"}:
        blockers.append("execution_mode_invalid")

    power = _as_float(plan.get("power_w"))
    if power is None or not 100.0 <= power <= 3500.0:
        blockers.append("power_out_of_range")

    target_soc = _as_float(plan.get("target_soc"))
    if target_soc is None or not 5.0 <= target_soc <= 100.0:
        blockers.append("target_soc_out_of_range")

    runtime = _as_float(plan.get("max_runtime_h"))
    if runtime is None or not 0.25 <= runtime <= 12.0:
        blockers.append("max_runtime_out_of_range")

    delay = _as_float(plan.get("max_start_delay_min"))
    if delay is None or not 1.0 <= delay <= 120.0:
        blockers.append("max_start_delay_out_of_range")

    if execution_mode == "gepland" or require_future_start:
        start = _parse_datetime(plan.get("start_time"))
        if start is None or start.tzinfo is None:
            blockers.append("start_time_required")
        elif now is not None:
            reference = now
            if reference.tzinfo is None:
                raise ValueError("now must be timezone-aware")
            if start <= reference:
                blockers.append("start_time_not_future")

    return blockers


def manual_plan_status(plan: Mapping[str, Any], *, now: datetime | None = None) -> str:
    """Return the user-facing R2 plan status without Scheduler semantics."""
    action = str(plan.get("action") or "geen")
    lifecycle = str(plan.get("lifecycle_status") or "concept").lower()

    if action == "geen":
        return "leeg"
    if lifecycle in TERMINAL_LIFECYCLES or lifecycle == "actief":
        return lifecycle
    if lifecycle == "concept":
        return "concept"

    blockers = validate_manual_plan(plan, now=now, require_future_start=False)
    if blockers:
        if blockers == ["start_time_not_future"]:
            return "starttijd_verstreken"
        if "start_time_required" in blockers:
            return "wacht_op_starttijd"
        return "ongeldig"

    if str(plan.get("execution_mode")) == "direct":
        return "direct_klaar"
    return "gepland"
