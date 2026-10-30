"""Read-only Alpha84 three-slot adapter for the existing Plan72 manual contract.

Never reinterpret an active or automatic plan as a manual instruction.
Invalid configured future manual actions fail closed instead of disappearing
silently from the projected SOC route.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite


def manual_constraints(store):
    rows = []
    for slot in range(1, 4):
        plan = store.get_plan(slot)
        if plan.get("origin") != "manual" or plan.get("execution_mode") != "gepland":
            continue
        if plan.get("action") not in {"laden", "ontladen"}:
            continue
        if plan.get("lifecycle_status") not in {"concept", "pending"}:
            continue
        try:
            start_dt = datetime.fromisoformat(str(plan["start_time"]).replace("Z", "+00:00"))
            if start_dt.tzinfo is None or start_dt.utcoffset() is None:
                raise ValueError("timezone_required")
            power = float(plan["power_w"])
            target = float(plan["target_soc"])
            runtime = float(plan["max_runtime_h"])
            if not all(map(isfinite, (power, target, runtime))):
                raise ValueError("nonfinite_manual_limits")
            if power <= 0 or runtime <= 0 or target < 0 or target > 100:
                raise ValueError("invalid_manual_limits")
        except (TypeError, ValueError, KeyError, OverflowError) as exc:
            raise ValueError(f"invalid_manual_slot_{slot}") from exc
        rows.append({
            "id": f"slot_{slot}",
            "action": "charge" if plan["action"] == "laden" else "discharge",
            "start_time": start_dt.astimezone(timezone.utc).isoformat(),
            "power_w": power,
            "target_soc": target,
            "max_runtime_h": runtime,
            "lifecycle_status": "pending",
        })
    return rows
