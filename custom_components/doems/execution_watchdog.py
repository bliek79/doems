"""Pure R8 active-session watchdog. Does not issue device commands."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from math import isfinite


def evaluate_session(*, now, started_at, action, target_soc, max_runtime_h, soc_percent, sources_fresh, controller_exclusive, command_acknowledged, plan_identity_matches, safety_clear):
    blockers = []
    if isinstance(started_at, str):
        try:
            started_at = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
        except ValueError:
            started_at = None
    if not isinstance(now, datetime) or not isinstance(started_at, datetime) or now.tzinfo is None or started_at.tzinfo is None or now.utcoffset() is None or started_at.utcoffset() is None or now < started_at:
        blockers.append("invalid_clock")
    try:
        target, runtime, soc = float(target_soc), float(max_runtime_h), float(soc_percent)
    except (ValueError, TypeError, OverflowError):
        target = runtime = soc = float("nan")
    if action not in ("laden", "ontladen"):
        blockers.append("invalid_action")
    if not isfinite(target) or not 5 <= target <= 100:
        blockers.append("invalid_target")
    if not isfinite(runtime) or not 0.25 <= runtime <= 12:
        blockers.append("invalid_runtime")
    if not isfinite(soc) or not 0 <= soc <= 100:
        blockers.append("soc_unavailable")
    if not sources_fresh:
        blockers.append("stale_sources")
    if not controller_exclusive:
        blockers.append("controller_conflict")
    if not command_acknowledged:
        blockers.append("command_ack_lost")
    if not plan_identity_matches:
        blockers.append("active_plan_changed")
    if not safety_clear:
        blockers.append("safety_blocked")
    if isinstance(now, datetime) and isinstance(started_at, datetime) and now.tzinfo and started_at.tzinfo and isfinite(runtime) and runtime > 0 and now >= started_at + timedelta(hours=runtime):
        blockers.append("runtime_elapsed")
    if isfinite(soc) and isfinite(target) and ((action == "laden" and soc >= target) or (action == "ontladen" and soc <= target)):
        blockers.append("target_reached")
    return {"decision": "stop" if blockers else "continue", "blockers": blockers, "execution_authority": False}
