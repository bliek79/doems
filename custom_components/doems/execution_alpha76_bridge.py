"""Read-only bridge from the proven Alpha76 EMS to R8 audit.

No commands, no authority, no inferred device acknowledgement.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping


def observe_alpha76(runtime: Any, now: datetime) -> dict[str, Any]:
    state = getattr(runtime, "data", {}) or {}
    if not isinstance(state, Mapping):
        state = {}
    soc = getattr(runtime, "soc_percent", None)
    try:
        soc = float(soc)
        if not isfinite(soc) or not 0 <= soc <= 100:
            soc = None
    except (TypeError, ValueError):
        soc = None
    updated = getattr(runtime, "soc_last_updated", None)
    try:
        measured = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
        age = (now.astimezone(timezone.utc) - measured.astimezone(timezone.utc)).total_seconds()
        fresh = 0 <= age <= 300
    except (TypeError, ValueError, AttributeError):
        fresh = False
    execution = getattr(runtime, "execution", None)
    observed = getattr(execution, "data", None)
    if not isinstance(observed, Mapping):
        observed = {}
    return {
        "battery": {
            "status": "ready" if soc is not None and fresh and
                      getattr(runtime, "soc_source_status", None) == "ok" else "blocked",
            "soc_percent": soc,
            # Direction is not proven by SOC alone: do not invent evidence.
            "direction_consistent": False,
        },
        "source_fresh": fresh and getattr(runtime, "soc_source_status", None) == "ok",
        "proven_execution": {
            "available": execution is not None,
            "active": observed.get("active") is True,
            "origin": observed.get("origin"),
            "slot": observed.get("slot"),
            "remaining_s": observed.get("remaining_s"),
            "setpoint_handoff_status": getattr(runtime, "_setpoint_handoff_status", None),
            "physical_owner": "alpha76" if execution is not None else None,
            "r8_command_issued": False,
        },
        "scheduler": dict(state),
    }
