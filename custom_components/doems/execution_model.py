"""Fail-closed execution state machine for the selected scheduler plan.

No Home Assistant imports or device writes. The physical control adapter is
deliberately absent until a separately authorized, device-specific handoff.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping


def _time(value: Any) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def evaluate_execution(
    *, now: datetime, scheduler: Mapping[str, Any],
    plan: Mapping[str, Any] | None, battery: Mapping[str, Any],
    source_fresh: bool, previous: Mapping[str, Any] | None = None,
    physical_execution_enabled: bool = False,
    execution_authority: bool = False,
    controller_ready: bool = False,
    controller_conflict: bool | None = None,
    device_acknowledged: bool = False,
    retries: int = 0,
) -> dict[str, Any]:
    """Evaluate start, prestart, final gate, monitoring and safe stop.

    A returned 'prepared' state is never evidence of device execution.
    No simulated running/completed state is possible without an acknowledged
    device command, a physical enable flag, and controller authority.
    """
    prev = previous or {}
    blockers: list[str] = []
    slot = scheduler.get("selected_slot")
    identity = (slot, scheduler.get("selected_origin"),
                scheduler.get("selected_planner_identity"),
                plan.get("lifecycle_updated_at") if isinstance(plan, Mapping) else None)
    base: dict[str, Any] = {
        "selected_slot": slot, "selected_origin": scheduler.get("selected_origin"),
        "action": plan.get("action") if isinstance(plan, Mapping) else None,
        "power_w": plan.get("power_w") if isinstance(plan, Mapping) else None,
        "target_soc": plan.get("target_soc") if isinstance(plan, Mapping) else None,
        "max_runtime_h": plan.get("max_runtime_h") if isinstance(plan, Mapping) else None,
        "physical_execution_enabled": bool(physical_execution_enabled),
        "execution_authority": bool(execution_authority),
        "execution_performed": False, "controller_ready": bool(controller_ready),
        "device_acknowledged": bool(device_acknowledged),
        "retries": retries, "max_retries": 2,
        "blockers": blockers, "scheduler_status": scheduler.get("status"),
        "plan_identity": str(identity), "safe_return_required": False,
    }
    def result(status: str, reason: str) -> dict[str, Any]:
        return {**base, "status": status, "reason": reason,
                "blockers": list(dict.fromkeys(blockers))}
    clock = _time(now)
    if clock is None:
        blockers.append("clock_invalid")
        return result("geblokkeerd", "Ongeldige klok")
    if type(slot) is not int or slot not in (1, 2, 3):
        return result("geen_actie", "Geen geselecteerd plan")
    if not isinstance(plan, Mapping):
        blockers.append("selected_plan_missing")
        return result("geblokkeerd", "Plan ontbreekt")
    for key, expected in (
        ("selected_action", plan.get("action")),
        ("selected_origin", plan.get("origin", "manual")),
        ("selected_lifecycle", plan.get("lifecycle_status")),
    ):
        if scheduler.get(key) != expected:
            blockers.append(f"{key}_changed")
    if scheduler.get("selected_origin") == "automatic_72h_planner":
        if scheduler.get("selected_planner_identity") != plan.get("planner_identity"):
            blockers.append("planner_identity_changed")
    if plan.get("lifecycle_status") != "pending":
        blockers.append("plan_not_pending")
    if scheduler.get("safety_status") != "safe" or scheduler.get("safety_blockers"):
        blockers.append("scheduler_safety_blocked")
    if scheduler.get("prestart_status") == "blocked" or scheduler.get("prestart_blockers"):
        blockers.append("scheduler_prestart_blocked")
    if scheduler.get("physical_execution_enabled") is not False or scheduler.get("execution_authority") is not False:
        blockers.append("scheduler_boundary_changed")
    if not source_fresh or battery.get("status") != "ready":
        blockers.append("battery_input_unavailable")
    if battery.get("direction_consistent") is not True or battery.get("status_direction_consistent") is False:
        blockers.append("battery_direction_conflict")
    if plan.get("action") not in ("laden", "ontladen"):
        blockers.append("action_invalid")
    power = _number(plan.get("power_w"))
    target = _number(plan.get("target_soc"))
    runtime = _number(plan.get("max_runtime_h"))
    soc = _number(battery.get("soc_percent"))
    if power is None or not 100 <= power <= 3500:
        blockers.append("power_invalid")
    if target is None or not 5 <= target <= 100:
        blockers.append("target_invalid")
    if runtime is None or not 0.25 <= runtime <= 12:
        blockers.append("runtime_invalid")
    if soc is None or not 0 <= soc <= 100:
        blockers.append("soc_invalid")
    if soc is not None and target is not None:
        if plan.get("action") == "laden" and soc >= target:
            blockers.append("charge_target_reached")
        if plan.get("action") == "ontladen" and soc <= target:
            blockers.append("discharge_target_reached")
    if plan.get("execution_mode") == "gepland":
        start, delay = _time(plan.get("start_time")), _number(plan.get("max_start_delay_min"))
        if start is None or delay is None or not 1 <= delay <= 120:
            blockers.append("start_window_invalid")
        elif not start <= clock <= start + timedelta(minutes=delay):
            blockers.append("outside_start_window")
    elif plan.get("execution_mode") != "direct" or plan.get("origin", "manual") != "manual":
        blockers.append("execution_mode_invalid")
    if controller_conflict is True:
        blockers.append("controller_conflict")
    if not isinstance(retries, int) or not 0 <= retries <= 2:
        blockers.append("retry_limit")
    if prev.get("status") in ("actief", "stoppen") and prev.get("plan_identity") != str(identity):
        blockers.append("active_plan_changed")
    if blockers:
        base["safe_return_required"] = prev.get("status") in ("actief", "stoppen")
        return result("stoppen" if base["safe_return_required"] else "geblokkeerd", "Veiligheids- of uitvoeringsvoorwaarde ontbreekt")
    if not physical_execution_enabled or not execution_authority:
        return result("voorbereid", "Voorbereid; fysieke uitvoering uitgeschakeld")
    if not controller_ready or controller_conflict is None:
        blockers.append("controller_evidence_missing")
        return result("geblokkeerd", "Controller niet onafhankelijk gevalideerd")
    if not device_acknowledged:
        return result("start_wacht_op_bevestiging", "Wacht op fysieke apparaatbevestiging")
    base["execution_performed"] = True
    return result("actief", "Fysieke start door apparaat bevestigd")
