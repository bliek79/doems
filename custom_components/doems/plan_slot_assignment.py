"""Alpha84-style rolling candidate-to-slot matching, with no storage writes.

The Chapter 6 three-item preview assumes free slots. This module maps the
complete eligible list against *actual* Alpha84 slot ownership, preserving
future matching automatic identities before allocating new actions.
Execution and Scheduler handoff remain disabled.
"""
from __future__ import annotations

from datetime import datetime, timezone


def _utc(value):
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("unaware_start_time")
    return stamp.astimezone(timezone.utc)


def _can_revise(plan, now):
    if plan.get("origin") != "automatic_72h_planner":
        return False
    status = plan.get("lifecycle_status")
    if status in {"concept", "voltooid", "geannuleerd", "fout"}:
        return True
    if status != "pending":
        return False
    try:
        return now < _utc(plan.get("start_time"))
    except (TypeError, ValueError, OverflowError):
        return False


def slot_assignment(store, bridge, *, now):
    """Return an observational desired slot map and rejected candidate reasons.

    Refuses invalid source generations. No mutation takes place here.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("unaware_now")
    now = now.astimezone(timezone.utc)
    if not bridge.get("valid") or bridge.get("status") not in {"ready", "limited", "idle"}:
        return {"valid": False, "reason": "bridge_not_ready", "desired": {}, "unassigned": []}
    if not bridge.get("source_input_fingerprint") or bridge.get("source_plan_generation") is None:
        return {"valid": False, "reason": "missing_source_identity", "desired": {}, "unassigned": []}
    existing = {i: store.get_plan(i) for i in range(1, 4)}
    available = [i for i in range(1, 4) if _can_revise(existing[i], now)
                 or existing[i].get("action") in (None, "geen")
                 and existing[i].get("lifecycle_status") not in {"actief", "pending"}]
    available = [i for i in available if existing[i].get("origin") == "automatic_72h_planner"
                 or existing[i].get("origin") == "manual" and existing[i].get("action") in (None, "geen")
                 and existing[i].get("lifecycle_status") == "concept"]
    candidates = bridge.get("eligible_candidates") or []
    desired, unassigned, used = {}, [], set()
    protected = {p.get("planner_identity") for i, p in existing.items()
                 if i not in available and p.get("planner_identity")}
    seen, eligible = set(), []
    for item in candidates:
        if not item.get("valid") or item.get("selection_status") != "eligible":
            continue
        identity = item.get("planner_identity")
        if not isinstance(identity, str) or not identity or identity in seen:
            unassigned.append({"identity": identity, "reason": "invalid_or_duplicate_identity"})
            continue
        seen.add(identity)
        if identity in protected:
            continue
        try:
            start = _utc(item["start_time"])
        except (KeyError, TypeError, ValueError, OverflowError):
            unassigned.append({"identity": identity, "reason": "invalid_start"})
            continue
        if start <= now:
            unassigned.append({"identity": identity, "reason": "start_due"})
            continue
        eligible.append((start, item))
    eligible.sort(key=lambda pair: (pair[0], pair[1]["planner_identity"]))
    selected = [item for _, item in eligible[:len(available)]]
    unassigned.extend({"identity": item["planner_identity"], "reason": "no_free_slot"}
                      for _, item in eligible[len(available):])
    # Reserve surviving identities only within the chronological selected prefix.
    # Reserving overflow would let a later action displace an earlier candidate.
    reserved = {item["planner_identity"]: slot for item in selected for slot in available
                if item["planner_identity"] == existing[slot].get("planner_identity")}
    for item in selected:
        identity = item["planner_identity"]
        slot = reserved.get(identity)
        if slot is None:
            slot = next(i for i in available if i not in used and i not in reserved.values())
        desired[slot] = item
        used.add(slot)
    return {"valid": True, "reason": "preview_only", "desired": desired,
            "unassigned": unassigned, "source_plan_generation": bridge["source_plan_generation"],
            "source_input_fingerprint": bridge["source_input_fingerprint"]}
