"""DOEMS R7: pure, non-actuating Scheduler / Safety / Prestart decisions."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
import math

from .automatic_plan_contract import validate_automatic_plan

AUTO_ORIGIN = "automatic_72h_planner"
TERMINAL = {"actief", "voltooid", "geannuleerd", "fout", "verlopen"}

def _time(value: Any) -> datetime | None:
    try:
        d = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None

def _num(value: Any) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None

def _safety(plan: Mapping[str, Any], battery: Mapping[str, Any],
            combined: Mapping[str, Any], source_fresh: bool,
            manual_limits: Mapping[str, Any] | None = None) -> list[str]:
    blockers: list[str] = []
    if battery.get("status") != "ready":
        blockers.append("battery_input_not_ready")
    if not source_fresh:
        blockers.append("battery_sources_stale")
    if battery.get("direction_consistent") is not True:
        blockers.append("battery_power_conflict")
    if battery.get("status_direction_consistent") is False:
        blockers.append("battery_device_status_conflict")
    capacity = _num(battery.get("capacity_kwh"))
    if capacity is None or capacity <= 0:
        blockers.append("battery_capacity_missing")
    action = plan.get("action")
    power, target, soc = (_num(plan.get("power_w")), _num(plan.get("target_soc")),
                          _num(battery.get("soc_percent")))
    limits = manual_limits if plan.get("origin", "manual") == "manual" else combined
    if limits is None:
        limits = {}
    maximum = _num(limits.get("max_charge_power_w" if action == "laden" else "max_discharge_power_w"))
    if action not in {"laden", "ontladen"}:
        blockers.append("action_invalid")
    if maximum is None or maximum <= 0 or power is None or not 100 <= power <= maximum:
        blockers.append("power_invalid")
    if target is None or not 5 <= target <= 100:
        blockers.append("target_soc_invalid")
    if soc is None or not 0 <= soc <= 100:
        blockers.append("live_soc_invalid")
    if soc is not None and target is not None:
        if action == "laden" and soc >= target:
            blockers.append("charge_target_already_reached")
        if action == "ontladen" and soc <= target:
            blockers.append("discharge_target_already_reached")
        if action == "ontladen":
            # R5 owns the hard floor; never derive it from a hardcoded capacity.
            reserve = _num(limits.get("planner_floor_soc_percent"))
            if reserve is None:
                blockers.append("execution_reserve_unavailable")
            elif soc <= reserve or target < reserve:
                blockers.append("execution_reserve_reached")
    return list(dict.fromkeys(blockers))

def evaluate_r7(*, now: datetime, plans: Mapping[int, Mapping[str, Any]],
                bundle: Mapping[str, Any], battery: Mapping[str, Any],
                bridge_ready: bool, planner_generation: int,
                source_fresh: bool, manual_limits: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Select one due plan; only an automatic concept can pass R7-D2 promotion."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    clock = now.astimezone(timezone.utc)
    candidates: list[tuple[int, datetime, int]] = []
    wakes: list[datetime] = []
    slots: dict[int, str] = {}
    for slot in (1, 2, 3):
        plan = plans.get(slot) or {}
        action = plan.get("action")
        origin = plan.get("origin", "manual")
        lifecycle = plan.get("lifecycle_status", "concept")
        if action not in {"laden", "ontladen"}:
            slots[slot] = "leeg" if action in (None, "geen") else "ongeldig"
            continue
        if lifecycle in TERMINAL:
            slots[slot] = str(lifecycle)
            continue
        if lifecycle not in {"concept", "pending"}:
            slots[slot] = "ongeldig"
            continue
        if lifecycle == "concept" and origin != AUTO_ORIGIN:
            slots[slot] = "handmatig_concept"
            continue
        if plan.get("execution_mode") == "direct" and origin == "manual" and lifecycle == "pending":
            slots[slot] = "due"
            candidates.append((1, clock, slot))
            continue
        if plan.get("execution_mode") != "gepland":
            slots[slot] = "ongeldig"
            continue
        start, margin = _time(plan.get("start_time")), _num(plan.get("max_start_delay_min"))
        if start is None or margin is None or not 1 <= margin <= 120:
            slots[slot] = "ongeldig"
            continue
        deadline = start + timedelta(minutes=margin)
        if clock < start:
            slots[slot] = "wachtend"
            wakes.append(start)
        elif clock <= deadline:
            slots[slot] = "due"
            candidates.append((0, start, slot))
            wakes.append(deadline + timedelta(seconds=1))
        else:
            slots[slot] = "verlopen_in_afwachting_r6"
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    selected_slot = candidates[0][2] if candidates else None
    selected = plans.get(selected_slot) if selected_slot is not None else None
    combined = bundle.get("combined") if isinstance(bundle.get("combined"), dict) else {}
    full_bundle = (
        bundle.get("status") == "ready" and bundle.get("valid") is True
        and bundle.get("planner_published_generation") == planner_generation
        and isinstance(bundle.get("automatic"), dict)
        and bundle["automatic"].get("valid") is True
        and bundle["automatic"].get("native_slot_count") == 288
        and combined.get("status") == "ready" and combined.get("valid") is True
        and combined.get("native_slot_count") == 288
    )
    auto_concept = bool(selected and selected.get("origin") == AUTO_ORIGIN
                        and selected.get("lifecycle_status") == "concept")
    safety_needed = bool(selected and selected.get("lifecycle_status") in {"concept", "pending"})
    safety_blockers = _safety(selected, battery, combined, source_fresh, manual_limits) if safety_needed else []
    prestart_blockers: list[str] = []
    if auto_concept:
        if not full_bundle:
            prestart_blockers.append("r5_bundle_not_current")
        if not bridge_ready:
            prestart_blockers.append("r6_bridge_not_ready")
        if not selected.get("planner_identity") or not selected.get("planner_signature"):
            prestart_blockers.append("automatic_identity_missing")
        if selected.get("execution_mode") != "gepland":
            prestart_blockers.append("execution_mode_invalid")
        # An R6 automatic segment may be exactly one native 15-minute slot.
        # Share the *same* contract as the Plan Store; Manual keeps 0.5 h.
        for issue in validate_automatic_plan(selected, now=now, require_due=True):
            prestart_blockers.append(f"automatic_contract_{issue}")
    can_promote = bool(auto_concept and not safety_blockers and not prestart_blockers)
    if selected is None:
        status = "wachtend" if wakes else "idle"
    elif auto_concept:
        status = "promotion_ready" if can_promote else "blocked"
    elif selected.get("origin") == AUTO_ORIGIN:
        status = "automatic_pending_observe"
    else:
        status = "manual_pending_observe"
    return {
        "status": status, "selected_slot": selected_slot,
        "selected_origin": selected.get("origin") if selected else None,
        "selected_action": selected.get("action") if selected else None,
        "selected_start_time": selected.get("start_time") if selected else None,
        "selected_planner_identity": selected.get("planner_identity") if selected else None,
        "selected_lifecycle": selected.get("lifecycle_status") if selected else None,
        "slots": slots, "next_wake_at": min(wakes).isoformat() if wakes else None,
        "safety_status": ("safe" if not safety_blockers else "blocked") if safety_needed else "not_required",
        "safety_blockers": safety_blockers,
        "prestart_status": ("safe" if not prestart_blockers else "blocked") if auto_concept else "not_required",
        "prestart_blockers": prestart_blockers,
        "r5_bundle_current": bool(full_bundle), "can_promote": can_promote,
        "physical_execution_enabled": False, "execution_authority": False,
    }
