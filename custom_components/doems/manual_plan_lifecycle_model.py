"""Pure manual Plan Store lifecycle/expiry semantics for DOEMS R4."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

MANUAL_EXPIRY_REASON = "manual_start_window_expired"
MANUAL_RELEASE_REASON = "manual_expired_released"


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _delay_minutes(value: Any) -> float | None:
    try:
        delay = float(value)
    except (TypeError, ValueError):
        return None
    if not 1.0 <= delay <= 120.0:
        return None
    return delay


def evaluate_manual_plan_expiry(
    plan: Mapping[str, Any],
    *,
    now: datetime,
    slot: int | None = None,
) -> dict[str, Any]:
    """Evaluate one slot without mutating it.

    Only manual-origin pending scheduled plans are expiry candidates. The
    complete start window remains valid through its exact end. Expiry starts
    only when now is strictly later than start + max_start_delay.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    origin = str(plan.get("origin") or "")
    lifecycle = str(plan.get("lifecycle_status") or "").lower()

    base = {
        "slot": slot,
        "applicable": False,
        "status": "ignored",
        "expired": False,
        "window_end": None,
        "blockers": [],
    }

    if origin != "manual" or lifecycle != "pending":
        return base

    blockers: list[str] = []
    action = str(plan.get("action") or "")
    execution_mode = str(plan.get("execution_mode") or "")
    start = _aware_datetime(plan.get("start_time"))
    delay = _delay_minutes(plan.get("max_start_delay_min"))

    prefix = f"manual_plan_{slot}_" if slot is not None else "manual_plan_"
    if action not in {"laden", "ontladen"}:
        blockers.append(prefix + "action_invalid")
    if execution_mode != "gepland":
        blockers.append(prefix + "execution_mode_invalid")
    if start is None:
        blockers.append(prefix + "start_time_invalid")
    if delay is None:
        blockers.append(prefix + "start_delay_invalid")

    if blockers:
        return {
            **base,
            "applicable": True,
            "status": "blocked",
            "blockers": blockers,
        }

    window_end = start + timedelta(minutes=delay)
    if now > window_end:
        status = "expired"
        expired = True
    elif now >= start:
        status = "start_window_open"
        expired = False
    else:
        status = "scheduled"
        expired = False

    return {
        **base,
        "applicable": True,
        "status": status,
        "expired": expired,
        "start_time": start.isoformat(),
        "window_end": window_end.isoformat(),
        "blockers": [],
    }


def next_manual_expiry_deadline(
    plans: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Return the earliest valid manual pending expiry boundary."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    deadlines: list[tuple[datetime, int]] = []
    blockers: list[str] = []
    for index, plan in enumerate(plans, start=1):
        result = evaluate_manual_plan_expiry(plan, now=now, slot=index)
        blockers.extend(str(value) for value in result.get("blockers", []))
        if not result.get("applicable") or result.get("status") == "blocked":
            continue
        raw = result.get("window_end")
        end = _aware_datetime(raw)
        if end is not None:
            deadlines.append((end, index))

    deadlines.sort(key=lambda item: (item[0], item[1]))
    if not deadlines:
        return {
            "deadline": None,
            "slot": None,
            "blockers": sorted(set(blockers)),
        }

    deadline, slot = deadlines[0]
    return {
        "deadline": deadline,
        "slot": slot,
        "blockers": sorted(set(blockers)),
    }
