"""Deterministic, fail-closed execution lifecycle.

This module owns the lifecycle and never sends a battery command. An actual
battery driver must implement an independently validated command/ack/stop
contract before physical execution can be enabled.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping


def _utc(value: Any) -> datetime | None:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo and dt.utcoffset() is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def evaluate_execution(*, now: datetime, scheduler: Mapping[str, Any],
                       plan: Mapping[str, Any] | None, battery: Mapping[str, Any],
                       source_fresh: bool, previous: Mapping[str, Any] | None = None,
                       physical_execution_enabled: bool = False,
                       execution_authority: bool = False,
                       controller_ready: bool = False,
                       controller_conflict: bool | None = None,
                       device_acknowledged: bool = False,
                       device_stopped: bool = False,
                       retries: int = 0) -> dict[str, Any]:
    prev = previous or {}
    clock = _utc(now)
    slot = scheduler.get("selected_slot")
    identity = (slot, scheduler.get("selected_origin"),
                scheduler.get("selected_planner_identity"),
                plan.get("lifecycle_updated_at") if isinstance(plan, Mapping) else None)
    key = repr(identity)
    previous_running = prev.get("status") in ("actief", "stoppen")
    blockers: list[str] = []
    result: dict[str, Any] = {
        "selected_slot": slot, "selected_origin": scheduler.get("selected_origin"),
        "action": plan.get("action") if isinstance(plan, Mapping) else None,
        "power_w": plan.get("power_w") if isinstance(plan, Mapping) else None,
        "target_soc": plan.get("target_soc") if isinstance(plan, Mapping) else None,
        "max_runtime_h": plan.get("max_runtime_h") if isinstance(plan, Mapping) else None,
        "plan_identity": key, "scheduler_status": scheduler.get("status"),
        "physical_execution_enabled": physical_execution_enabled,
        "execution_authority": execution_authority,
        "execution_performed": False,
        "device_acknowledged": device_acknowledged,
        "controller_ready": controller_ready,
        "retries": retries, "max_retries": 2,
        "safe_return_required": False, "blockers": blockers,
        "status": "geblokkeerd", "reason": "Controle onvolledig",
    }
    def finish(status: str, reason: str) -> dict[str, Any]:
        result["status"], result["reason"] = status, reason
        result["blockers"] = list(dict.fromkeys(blockers))
        return result
    if prev.get("safe_return_required") and prev.get("status") == "geblokkeerd":
        blockers.append("restart_requires_reconciliation")
        result["safe_return_required"] = True
        return finish("geblokkeerd", "Handmatige apparaatcontrole na herstart vereist")
    if prev.get("status") == "stoppen":
        result["safe_return_required"] = not device_stopped
        return finish("gestopt" if device_stopped else "stoppen",
                      "Stop bevestigd" if device_stopped else "Veilige stop wacht op apparaatbevestiging")
    if clock is None:
        blockers.append("clock_invalid")
    if type(slot) is not int or slot not in (1, 2, 3):
        blockers.append("selection_missing")
    if not isinstance(plan, Mapping):
        blockers.append("selected_plan_missing")
    else:
        for field, expected in (
            ("selected_action", plan.get("action")),
            ("selected_origin", plan.get("origin", "manual")),
            ("selected_lifecycle", plan.get("lifecycle_status")),
        ):
            if scheduler.get(field) != expected:
                blockers.append(field + "_changed")
        if scheduler.get("selected_origin") == "automatic_72h_planner" and scheduler.get("selected_planner_identity") != plan.get("planner_identity"):
            blockers.append("planner_identity_changed")
        if plan.get("lifecycle_status") != "pending":
            blockers.append("plan_not_pending")
        if plan.get("action") not in ("laden", "ontladen"):
            blockers.append("action_invalid")
        power, target, runtime = (_number(plan.get("power_w")), _number(plan.get("target_soc")), _number(plan.get("max_runtime_h")))
        if power is None or not 100 <= power <= 3500:
            blockers.append("power_invalid")
        if target is None or not 5 <= target <= 100:
            blockers.append("target_invalid")
        if runtime is None or not 0.25 <= runtime <= 12:
            blockers.append("runtime_invalid")
        if plan.get("execution_mode") == "gepland":
            start, delay = _utc(plan.get("start_time")), _number(plan.get("max_start_delay_min"))
            if start is None or delay is None or not 1 <= delay <= 120:
                blockers.append("start_window_invalid")
            elif clock is not None and not previous_running and not start <= clock <= start + timedelta(minutes=delay):
                blockers.append("outside_start_window")
        elif plan.get("execution_mode") != "direct" or plan.get("origin", "manual") != "manual":
            blockers.append("execution_mode_invalid")
        if previous_running and prev.get("plan_identity") == key:
            started = _utc(prev.get("started_at"))
            if started is None:
                blockers.append("start_evidence_missing")
            elif clock is not None and runtime is not None and clock >= started + timedelta(hours=runtime):
                blockers.append("runtime_elapsed")
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
    soc, target = _number(battery.get("soc_percent")), _number(plan.get("target_soc")) if isinstance(plan, Mapping) else None
    if soc is None or not 0 <= soc <= 100:
        blockers.append("soc_invalid")
    elif target is not None and isinstance(plan, Mapping):
        if plan.get("action") == "laden" and soc >= target:
            blockers.append("charge_target_reached")
        if plan.get("action") == "ontladen" and soc <= target:
            blockers.append("discharge_target_reached")
    if previous_running and prev.get("plan_identity") != key:
        blockers.append("active_plan_changed")
    if controller_conflict is True:
        blockers.append("controller_conflict")
    if type(retries) is not int or not 0 <= retries <= 2:
        blockers.append("retry_limit")
    if blockers:
        if previous_running:
            result["safe_return_required"] = not device_stopped
            return finish("gestopt" if device_stopped else "stoppen", "Veilige terugkeer vereist")
        return finish("geen_actie" if blockers == ["selection_missing"] else "geblokkeerd", "Uitvoeringsvoorwaarden niet voldaan")
    if not physical_execution_enabled or not execution_authority:
        if previous_running:
            result["safe_return_required"] = not device_stopped
            return finish("gestopt" if device_stopped else "stoppen", "Uitvoering uitgeschakeld; veilige terugkeer")
        return finish("voorbereid", "Scheduler en veiligheid akkoord; fysieke uitvoering uitgeschakeld")
    if not controller_ready or controller_conflict is None:
        blockers.append("controller_evidence_missing")
        if previous_running:
            result["safe_return_required"] = not device_stopped
            return finish("gestopt" if device_stopped else "stoppen", "Controllerbevestiging verloren")
        return finish("geblokkeerd", "Controller niet onafhankelijk gevalideerd")
    if not device_acknowledged:
        if previous_running:
            result["safe_return_required"] = not device_stopped
            return finish("gestopt" if device_stopped else "stoppen", "Apparaatbevestiging verloren")
        return finish("start_wacht_op_bevestiging", "Wacht op apparaatbevestiging")
    result["execution_performed"] = True
    result["started_at"] = prev.get("started_at") if previous_running else clock.isoformat()
    return finish("actief", "Uitvoering bevestigd door apparaat")
