"""Battery-specific control-path contract; observation only until separately authorized.

The historical Anker EMS uses three HA controls: operating mode, direction and
power setpoint. This module validates those controls without issuing commands.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping

EXTERNAL_MODE = "third_party_control"
SELF_MODE = "self_consumption"
REQUIRED_STABILITY_SECONDS = 60


def _state(hass: Any, entity_id: str, now: datetime) -> dict[str, Any]:
    state = hass.states.get(entity_id) if entity_id else None
    if state is None or state.state in ("unknown", "unavailable"):
        return {"entity_id": entity_id, "available": False, "value": None, "stable_seconds": 0.0}
    changed = getattr(state, "last_changed", None)
    stable = max(0.0, (now.astimezone(timezone.utc) - changed.astimezone(timezone.utc)).total_seconds()) if isinstance(changed, datetime) and changed.tzinfo else 0.0
    return {"entity_id": entity_id, "available": True, "value": state.state, "stable_seconds": stable}


def observe_control_path(hass: Any, entities: Mapping[str, str], now: datetime) -> dict[str, Any]:
    """Pre-mode readiness and post-mode 60-second readiness, never authority."""
    names = ("operating_mode", "action_direction", "power_setpoint")
    prefixes = ("select.", "select.", "number.")
    errors = [f"{key}_not_configured" for key, prefix in zip(names, prefixes)
              if not str(entities.get(key) or "").startswith(prefix)]
    if errors:
        return {"ready": False, "pre_mode_ready": False, "post_mode_ready": False,
                "blockers": errors, "physical_execution_enabled": False}
    details = {key: _state(hass, entities[key], now) for key in names}
    mode = details["operating_mode"]
    pre = mode["available"] and mode["stable_seconds"] >= REQUIRED_STABILITY_SECONDS
    external = mode["value"] == EXTERNAL_MODE
    post = external and all(details[key]["available"] and
                            details[key]["stable_seconds"] >= REQUIRED_STABILITY_SECONDS
                            for key in ("action_direction", "power_setpoint"))
    blockers: list[str] = []
    if not pre:
        blockers.append("operating_mode_not_stable_or_unavailable")
    if external and not post:
        blockers.append("external_controls_not_stable_or_unavailable")
    return {"ready": pre and (post if external else True), "pre_mode_ready": pre,
            "post_mode_ready": post, "external_mode_active": external,
            "blockers": blockers, "entities": details,
            "physical_execution_enabled": False, "execution_authority": False}
