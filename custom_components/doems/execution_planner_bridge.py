"""Read-only R8 planner bridge.

Normalizes scheduler selection into a stable audit record. It never invokes a
controller or battery adapter and never grants execution authority.
"""
from __future__ import annotations

from typing import Any, Mapping


def inspect_selection(scheduler: Mapping[str, Any],
                      plan: Mapping[str, Any] | None) -> dict[str, Any]:
    slot = scheduler.get("selected_slot")
    blockers: list[str] = []
    if type(slot) is not int or slot not in (1, 2, 3):
        blockers.append("selection_missing")
    if not isinstance(plan, Mapping):
        blockers.append("selected_plan_missing")
        plan = {}
    for key, field in (("selected_action", "action"),
                       ("selected_lifecycle", "lifecycle_status")):
        if scheduler.get(key) != plan.get(field):
            blockers.append(key + "_changed")
    origin = plan.get("origin", "manual")
    if scheduler.get("selected_origin") != origin:
        blockers.append("selected_origin_changed")
    if origin == "automatic_72h_planner" and (
        scheduler.get("selected_planner_identity") != plan.get("planner_identity")
    ):
        blockers.append("planner_identity_changed")
    identity = (
        slot, scheduler.get("selected_origin"),
        scheduler.get("selected_planner_identity"),
        plan.get("lifecycle_updated_at"),
    )
    return {
        "identity": repr(identity),
        "selected_slot": slot,
        "selected_origin": scheduler.get("selected_origin"),
        "ready": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "execution_authority": False,
        "physical_execution_enabled": False,
    }
