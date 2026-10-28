"""Common fail-closed prestart battery safety checks for Manual and Automatic R8."""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def common_prestart_blockers(
    plan: Mapping[str, Any], snapshot: Mapping[str, Any],
    limits: Mapping[str, Any], *, sources_fresh: bool,
) -> list[str]:
    """Identical physical safety gates independent of plan origin.

    Automatic-only forecast, identity and economic gates remain additional.
    """
    blockers: list[str] = []
    action = plan.get("action")
    power = _number(plan.get("power_w"))
    target = _number(plan.get("target_soc"))
    soc = _number(snapshot.get("soc_percent"))
    charge = _number(snapshot.get("charge_power_w"))
    discharge = _number(snapshot.get("discharge_power_w"))
    configured = _number(limits.get(
        "max_charge_power_w" if action == "laden" else "max_discharge_power_w"
    ))

    if not sources_fresh or snapshot.get("status") != "ready":
        blockers.append("battery_sources_not_ready")
    if action not in ("laden", "ontladen"):
        blockers.append("invalid_action")
    if (power is None or power != int(power) or power < 100
            or configured is None or configured < 100
            or power > min(3500, configured)):
        blockers.append("invalid_power_limit")
    if target is None or not 5 <= target <= 100:
        blockers.append("invalid_target_soc")
    if soc is None or not 0 <= soc <= 100:
        blockers.append("invalid_soc")
    if charge is None or discharge is None or charge < 0 or discharge < 0:
        blockers.append("battery_power_unavailable")
    elif charge > 100 and discharge > 100:
        blockers.append("conflicting_battery_power")
    if soc is not None and target is not None and 0 <= soc <= 100:
        if action == "laden" and soc >= target:
            blockers.append("charge_target_already_reached")
        if action == "ontladen" and (soc <= 5 or soc <= target):
            blockers.append("discharge_reserve_or_target_reached")
    if action == "laden" and discharge is not None and discharge > 100:
        blockers.append("unexpected_discharge")
    if action == "ontladen" and charge is not None and charge > 100:
        blockers.append("unexpected_charge")
    return blockers
