"""Evidence audit for P2 point 1: no unrelated Alpha84 candidate can approve DOEMS.

This module only compares snapshots and returns a verdict. It never mutates
either planner, claims authority, or sends commands.
"""
from __future__ import annotations
from typing import Any, Mapping

from .alpha84_handoff_contract import HandoffContractError


def audit_plan_lineage(
    doems_plan: Mapping[str, Any],
    projected: Mapping[str, Any],
    original_live: Mapping[str, Any],
    *, verified_doems_candidate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    slot = projected.get("scheduler_selected_slot")
    detail = (projected.get("scheduler_slots") or {}).get(slot)
    if not isinstance(detail, dict):
        raise HandoffContractError("Projected plan missing")
    identity = detail.get("planner_identity")
    revision = detail.get("planner_signature")
    if not identity or not revision:
        raise HandoffContractError("DOEMS planner identity or revision missing")
    if doems_plan.get("planner_identity") != identity or doems_plan.get("planner_signature") != revision:
        raise HandoffContractError("DOEMS plan identity changed during projection")
    if (doems_plan.get("action") != detail.get("action")
            or doems_plan.get("power_w") != detail.get("power_w")
            or float(doems_plan.get("target_soc", -1)) != detail.get("target_soc")):
        raise HandoffContractError("DOEMS plan action changed during projection")
    candidates = ([verified_doems_candidate] if verified_doems_candidate is not None else
                  (original_live.get("auto_bridge_candidates") or []) +
                  (original_live.get("auto_bridge_slot_preview") or []))
    matching = [c for c in candidates if isinstance(c, dict) and c.get("planner_identity") == identity]
    if len(matching) != 1:
        raise HandoffContractError("Expected one authoritative original candidate")
    candidate = matching[0]
    for key in ("planner_signature", "action", "power_w", "target_soc"):
        if candidate.get(key) != detail.get(key):
            raise HandoffContractError(f"Original candidate mismatch: {key}")
    return {
        "lineage": ("matched_against_verified_r6_candidate" if verified_doems_candidate is not None
                    else "matched_against_existing_original_candidate"),
        "planner_identity": identity,
        "planner_signature": revision,
        "physical_execution_enabled": False,
    }
