"""Read-only, fail-closed legacy Anker EMS safety evidence for acknowledgement.

Entity IDs are discovered via the existing anker_ems entity registry.
No legacy entity IDs or user-supplied safety flags are assumed.
"""
from __future__ import annotations

from homeassistant.helpers import entity_registry as er

_LEGACY_KEYS = {
    "arm": ("switch", "automatic_execution_arm"),
    "execution": ("sensor", "execution_status"),
    "physical_test": ("sensor", "physical_test_status"),
    "preflight": ("sensor", "automatic_execution_preflight"),
}


def read_legacy_safety(hass) -> dict:
    registry = er.async_get(hass)
    resolved = {}
    for role, (domain, suffix) in _LEGACY_KEYS.items():
        matches = [
            entity.entity_id
            for entity in registry.entities.values()
            if entity.platform == "anker_ems"
            and entity.domain == domain
            and entity.unique_id.endswith("_" + suffix)
            and not entity.disabled_by
        ]
        if len(matches) != 1:
            raise ValueError(f"Legacy EMS safety source {role} missing or ambiguous")
        resolved[role] = matches[0]

    observed = {}
    for role, entity_id in resolved.items():
        state = hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", ""):
            raise ValueError(f"Legacy EMS safety source {role} unavailable")
        observed[role] = state

    arm = observed["arm"]
    if arm.state != "off":
        raise ValueError("Legacy automatic execution not confirmed off")

    for role in ("execution", "physical_test"):
        if observed[role].attributes.get("active") is not False:
            raise ValueError(f"Legacy EMS {role} not confirmed inactive")

    if observed["preflight"].attributes.get("mode_switch_live_active") is not False:
        raise ValueError("Legacy EMS mode switch not confirmed inactive")

    return {"automatic_armed": False, "physical_test": {"active": False}}
