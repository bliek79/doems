"""Read-only Alpha84 three-slot adapter for the existing Plan72 manual contract.

Never reinterpret an active or automatic plan as a manual instruction.
Invalid configured future manual actions fail closed instead of disappearing
silently from the projected SOC route.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite


def manual_constraints(store, *, now=None):
    rows = []
    for slot in range(1, 4):
        plan = store.get_plan(slot)
        automatic = plan.get("origin") == "automatic_72h_planner"
        status = plan.get("lifecycle_status")
        if status not in {"concept", "pending", "actief"}:
            continue
        if plan.get("action") in {None, "geen"}:
            continue
        if plan.get("action") not in {"laden", "ontladen"}:
            raise ValueError(f"invalid_manual_slot_{slot}")
        mode = plan.get("execution_mode")
        if mode not in {"direct", "gepland"}:
            raise ValueError(f"invalid_manual_slot_{slot}")
        if mode == "direct" and status == "concept":
            continue
        if automatic and status not in {"pending", "actief"}:
            continue
        try:
            start_dt = datetime.fromisoformat(str(plan["start_time"]).replace("Z", "+00:00"))
            if start_dt.tzinfo is None or start_dt.utcoffset() is None:
                raise ValueError("timezone_required")
            if automatic and status == "pending" and (now is None or start_dt > now):
                continue
            if automatic:
                purpose = plan.get("purpose")
                expected = "ontladen" if purpose == "trade_discharge" else "laden"
                if purpose not in {"safety_charge", "trade_charge", "trade_discharge"} or plan["action"] != expected:
                    raise ValueError("invalid_automatic_purpose")
            power = float(plan["power_w"])
            target = float(plan.get("command_target_soc") if automatic and plan.get("command_target_soc") is not None else plan["target_soc"])
            runtime = float(plan["max_runtime_h"])
            if not all(map(isfinite, (power, target, runtime))):
                raise ValueError("nonfinite_manual_limits")
            if power <= 0 or runtime <= 0 or target < 0 or target > 100:
                raise ValueError("invalid_manual_limits")
        except (TypeError, ValueError, KeyError, OverflowError) as exc:
            raise ValueError(f"invalid_manual_slot_{slot}") from exc
        if automatic and plan.get("planned_end_time"):
            end_dt = datetime.fromisoformat(str(plan["planned_end_time"]).replace("Z", "+00:00"))
            if end_dt.tzinfo is None or end_dt <= start_dt:
                raise ValueError(f"invalid_automatic_slot_{slot}")
            runtime = min(runtime, (end_dt - start_dt).total_seconds() / 3600)
        if now is not None and status != "actief" and start_dt < now:
            delay = float(plan.get("max_start_delay_min", 5))
            if (now - start_dt).total_seconds() > delay * 60:
                continue
        rows.append({
            "id": f"slot_{slot}",
            "action": "charge" if plan["action"] == "laden" else "discharge",
            "start_time": start_dt.astimezone(timezone.utc).isoformat(),
            "power_w": power,
            "target_soc": target,
            "max_runtime_h": runtime,
            "lifecycle_status": "active" if status == "actief" or (now is not None and start_dt < now) else "pending",
            "power_start_time": plan.get("power_start_time") if automatic else None,
            "origin": ("safety" if plan.get("purpose") in {"safety", "safety_charge"} else "trade") if automatic else "manual",
        })
    return rows
