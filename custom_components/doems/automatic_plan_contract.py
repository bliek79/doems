"""R6 automatic quarter-hour plan contract; Manual validator remains separate."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Mapping, Any
import math

AUTO_ORIGIN = "automatic_72h_planner"
MIN_AUTO_RUNTIME_H = 0.25
MAX_AUTO_RUNTIME_H = 12.0

def _number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None

def _time(value):
    try:
        v = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return v.astimezone(timezone.utc) if v.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None

def validate_automatic_plan(plan: Mapping[str, Any], *, now=None, require_due=False):
    """Check an R6 slot without using Manual's 30-minute restriction."""
    issues = []
    if plan.get("origin") != AUTO_ORIGIN:
        issues.append("automatic_origin_invalid")
    if plan.get("action") not in ("laden", "ontladen"):
        issues.append("action_required")
    if plan.get("execution_mode") != "gepland":
        issues.append("execution_mode_invalid")
    power = _number(plan.get("power_w"))
    target = _number(plan.get("target_soc"))
    duration = _number(plan.get("max_runtime_h"))
    delay = _number(plan.get("max_start_delay_min"))
    start = _time(plan.get("start_time"))
    end = _time(plan.get("planned_end_time"))
    if power is None or not 100 <= power <= 3500:
        issues.append("power_out_of_range")
    if target is None or not 5 <= target <= 100:
        issues.append("target_soc_out_of_range")
    valid = duration is not None and MIN_AUTO_RUNTIME_H <= duration <= MAX_AUTO_RUNTIME_H
    if not valid:
        issues.append("max_runtime_out_of_range")
    elif abs(duration * 4 - round(duration * 4)) > 0.0001:
        issues.append("runtime_not_quarter_aligned")
    if start is None:
        issues.append("start_time_required")
    if end is None or start is None or end <= start:
        issues.append("planned_end_invalid")
    elif valid and abs((end-start).total_seconds()/3600-duration) > 0.00005:
        issues.append("duration_end_mismatch")
    if delay is None or not 1 <= delay <= 120:
        issues.append("max_start_delay_out_of_range")
    if require_due:
        if now is None or now.tzinfo is None:
            issues.append("clock_invalid")
        elif start is not None and delay is not None and 1 <= delay <= 120:
            clock = now.astimezone(timezone.utc)
            if clock < start:
                issues.append("start_not_reached")
            elif clock > start + timedelta(minutes=delay):
                issues.append("start_window_expired")
    return issues
