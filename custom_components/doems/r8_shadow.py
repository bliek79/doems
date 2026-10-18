"""R8 shadow action preparation from R7 selection.

Based on the historical Anker EMS action_controller preparation semantics.
No device control, no scheduling, no plan lifecycle changes.
"""
from __future__ import annotations

from typing import Any, Mapping


def evaluate_r8_shadow(r7: Mapping[str, Any], plan: Mapping[str, Any] | None) -> dict[str, Any]:
    """Observe R7's current selection and prepare an action without executing."""
    base: dict[str, Any] = {
        "physical_execution_enabled": False,
        "execution_authority": False,
        "execution_performed": False,
        "selected_slot": r7.get("selected_slot"),
        "action": None,
        "power_w": None,
        "target_soc": None,
        "max_runtime_h": None,
        "blockers": [],
    }
    slot = r7.get("selected_slot")
    if type(slot) is not int or slot not in (1, 2, 3):
        return {**base, "status": "geen_actie", "reason": "Geen startklaar plan"}
    if not isinstance(plan, Mapping):
        return {**base, "status": "geblokkeerd", "blockers": ["selected_plan_missing"]}
    blockers: list[str] = []
    if r7.get("selected_action") != plan.get("action"):
        blockers.append("selected_action_changed")
    if r7.get("selected_origin") != plan.get("origin", "manual"):
        blockers.append("selected_origin_changed")
    if r7.get("selected_lifecycle") != plan.get("lifecycle_status"):
        blockers.append("selected_lifecycle_changed")
    if plan.get("lifecycle_status") != "pending":
        blockers.append("plan_not_pending")
    if r7.get("safety_status") != "safe":
        blockers.append("r7_safety_not_safe")
    blockers.extend(str(x) for x in (r7.get("safety_blockers") or []))
    if r7.get("prestart_status") == "blocked":
        blockers.extend(str(x) for x in (r7.get("prestart_blockers") or []))
    if r7.get("physical_execution_enabled") is not False or r7.get("execution_authority") is not False:
        blockers.append("r7_execution_boundary_changed")
    if plan.get("action") not in ("laden", "ontladen"):
        blockers.append("action_invalid")
    for field in ("power_w", "target_soc", "max_runtime_h"):
        value = plan.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            blockers.append(f"{field}_missing")
    if not blockers:
        # No independent prestart approval is claimed for pending plans.
        return {
            **base, "status": "voorbereid",
            "reason": "Scheduler en veiligheid akkoord; fysieke uitvoering uitgeschakeld",
            "action": plan.get("action"),
            "power_w": plan.get("power_w"),
            "target_soc": plan.get("target_soc"),
            "max_runtime_h": plan.get("max_runtime_h"),
        }
    return {**base, "status": "geblokkeerd", "blockers": list(dict.fromkeys(blockers)),
            "reason": "Schedulerselectie of veiligheidsvoorwaarden niet akkoord"}
