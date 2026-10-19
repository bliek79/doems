"""Read-only R8 planner bridge.

Normalizes scheduler selection into a stable audit record. It never invokes a
controller or battery adapter and never grants execution authority.
"""
from __future__ import annotations

from typing import Any, Mapping


def inspect_selection(scheduler: Mapping[str, Any],
                      plan: Mapping[str, Any] | None) -> dict[str, Any]:
    is_r7 = "scheduler_selected_slot" in scheduler
    slot = scheduler.get("scheduler_selected_slot") if is_r7 else scheduler.get("selected_slot")
    slots = scheduler.get("scheduler_slots") or {}
    detail = (slots.get(slot) or slots.get(str(slot)) or {}) if is_r7 and isinstance(slots, Mapping) else {}
    action = scheduler.get("scheduler_selected_action") if is_r7 else scheduler.get("selected_action")
    lifecycle = detail.get("lifecycle_status") if is_r7 else scheduler.get("selected_lifecycle")
    selected_origin = detail.get("origin") if is_r7 else scheduler.get("selected_origin")
    selected_identity = detail.get("planner_identity") if is_r7 else scheduler.get("selected_planner_identity")
    blockers: list[str] = []
    if type(slot) is not int or slot not in (1, 2, 3):
        blockers.append("selection_missing")
    if is_r7:
        if scheduler.get("scheduler_ready") is not True:
            blockers.append("scheduler_not_ready")
        if detail.get("selected") is not True or detail.get("status") != "startklaar":
            blockers.append("scheduler_selection_not_confirmed")
        if detail.get("slot") != slot or detail.get("action") != action:
            blockers.append("scheduler_slot_detail_mismatch")
    if not isinstance(plan, Mapping):
        blockers.append("selected_plan_missing")
        plan = {}
    if not plan.get("action") or action != plan.get("action"):
        blockers.append("selected_action_changed")
    if not plan.get("lifecycle_status") or lifecycle != plan.get("lifecycle_status"):
        blockers.append("selected_lifecycle_changed")
    if plan.get("slot") is not None and plan.get("slot") != slot:
        blockers.append("selected_slot_changed")
    origin = plan.get("origin", "manual")
    if selected_origin != origin:
        blockers.append("selected_origin_changed")
    if origin == "automatic_72h_planner" and (
        selected_identity != plan.get("planner_identity")
    ):
        blockers.append("planner_identity_changed")
    identity = (
        slot, selected_origin,
        selected_identity,
        plan.get("lifecycle_updated_at"),
    )
    return {
        "identity": repr(identity),
        "selected_slot": slot,
        "selected_origin": selected_origin,
        "ready": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "execution_authority": False,
        "physical_execution_enabled": False,
    }
