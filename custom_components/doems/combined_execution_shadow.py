"""R9 Combined execution shadow observer.

No Home Assistant services are called. No physical battery authority exists here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def evaluate_combined_execution_shadow(
    snapshot: Mapping[str, Any], *, now: datetime
) -> dict[str, Any]:
    """Observe exactly one current native 15-minute slot, fail closed."""
    result: dict[str, Any] = {
        "status": "blocked",
        "reason": "invalid_snapshot",
        "physical_execution_enabled": False,
        "execution_performed": False,
        "source": "combined",
        "slot": None,
        "action": "idle",
    }
    if now.tzinfo is None:
        return {**result, "reason": "naive_clock"}
    if not isinstance(snapshot, Mapping) or snapshot.get("valid") is not True:
        return result
    if snapshot.get("blockers"):
        return {**result, "reason": "planner_blockers"}
    slots = snapshot.get("native_slots")
    if not isinstance(slots, list) or len(slots) != 288:
        return {**result, "reason": "native_288_required"}
    current = now.astimezone(timezone.utc)
    active: list[tuple[int, Mapping[str, Any]]] = []
    for position, slot in enumerate(slots):
        if not isinstance(slot, Mapping):
            return {**result, "reason": "malformed_slot"}
        start, end = _instant(slot.get("start")), _instant(slot.get("end"))
        if start is None or end is None or (end - start).total_seconds() != 900:
            return {**result, "reason": "invalid_quarter_boundaries"}
        if start <= current < end:
            active.append((position, slot))
    if len(active) != 1:
        return {**result, "reason": "no_unique_active_slot"}
    position, slot = active[0]
    manual_charge = float(slot.get("manual_charge_kwh") or 0)
    manual_discharge = float(slot.get("manual_discharge_kwh") or 0)
    automatic_charge = float(slot.get("charge_from_grid_safety_kwh") or 0) + float(
        slot.get("charge_from_grid_trade_kwh") or 0
    )
    automatic_discharge = float(slot.get("discharge_to_grid_kwh") or 0)
    if min(manual_charge, manual_discharge, automatic_charge, automatic_discharge) < 0:
        return {**result, "reason": "negative_energy"}
    charge = manual_charge + automatic_charge
    discharge = manual_discharge + automatic_discharge
    if charge > 0 and discharge > 0:
        return {**result, "reason": "conflicting_directions"}
    action = "charge" if charge > 0 else "discharge" if discharge > 0 else "idle"
    return {
        **result,
        "status": "shadow_ready",
        "reason": "observation_only",
        "slot": position,
        "action": action,
        "planned_energy_kwh": charge if charge else discharge,
        "planned_power_w": round((charge if charge else discharge) * 4000),
        "start": slot["start"],
        "end": slot["end"],
    }
