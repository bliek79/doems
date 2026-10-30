"""Read-only adapter from Alpha84 Plan Store slots to existing Plan72 manual contract."""
from __future__ import annotations

from datetime import datetime, timezone

def manual_constraints(store):
    """Only configured, prospective, manual scheduled actions affect Plan72.

    Drafts are not physical commitments. Do not convert current active plans
    until a validated execution-state handoff exists.
    """
    rows = []
    for slot in range(1, 4):
        plan = store.get_plan(slot)
        if plan.get("origin") != "manual" or plan.get("execution_mode") != "gepland":
            continue
        if plan.get("action") not in {"laden", "ontladen"}:
            continue
        if plan.get("lifecycle_status") not in {"pending"}:
            continue
        start = plan.get("start_time")
        if not start:
            continue
        try:
            start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            if start_dt.tzinfo is None or start_dt.utcoffset() is None:
                continue
            start = start_dt.astimezone(timezone.utc).isoformat()
            power = float(plan["power_w"])
            target = float(plan["target_soc"])
            runtime = float(plan["max_runtime_h"])
        except (TypeError, ValueError, KeyError):
            continue
        rows.append({"id": f"slot_{slot}", "action": "charge" if plan["action"] == "laden" else "discharge",
                     "start_time": start, "power_w": power, "target_soc": target,
                     "max_runtime_h": runtime, "lifecycle_status": "pending"})
    return rows
