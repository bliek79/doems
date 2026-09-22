"""Read-only DOEMS Step 12.1 control-path contract and readiness observer."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ACTION_DIRECTION_ENTITY,
    CONF_OPERATING_MODE_ENTITY,
    CONF_POWER_SETPOINT_ENTITY,
    CONTROL_PATH_STABLE_SECONDS,
)

_EXTERNAL_MODE = "third_party_control"
_UNAVAILABLE_STATES = {"unknown", "unavailable"}


class DOEMSControlPathObserver:
    """Observe the configured battery control path without actuating it.

    This is Step 12.1 only. It copies the working two-stage readiness contract
    from the current EMS source while deliberately exposing no service-call
    methods and no physical execution authority.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

    @property
    def entity_ids(self) -> dict[str, str | None]:
        return {
            "operating_mode": self._option(CONF_OPERATING_MODE_ENTITY),
            "action_direction": self._option(CONF_ACTION_DIRECTION_ENTITY),
            "power_setpoint": self._option(CONF_POWER_SETPOINT_ENTITY),
        }

    def _option(self, key: str) -> str | None:
        value = self.entry.options.get(key)
        return str(value) if value else None

    def configured_entity_ids(self) -> tuple[str, str, str]:
        ids = self.entity_ids
        mode = ids["operating_mode"]
        direction = ids["action_direction"]
        power = ids["power_setpoint"]
        if not mode or not direction or not power:
            raise ValueError("Niet alle besturingsentiteiten zijn geconfigureerd")
        if not mode.startswith("select."):
            raise ValueError("Bedrijfsmodus moet een select-entiteit zijn")
        if not direction.startswith("select."):
            raise ValueError("Laad/ontlaadrichting moet een select-entiteit zijn")
        if not power.startswith("number."):
            raise ValueError("Vermogenssetpoint moet een number-entiteit zijn")
        return mode, direction, power

    def evaluate(self) -> dict[str, Any]:
        """Return the source-parity two-stage readiness snapshot."""
        try:
            mode_entity, direction_entity, power_entity = self.configured_entity_ids()
        except ValueError as err:
            reason = str(err)
            return {
                "configured": False,
                "ready": False,
                "reason": reason,
                "stable_seconds": 0,
                "required_stable_seconds": CONTROL_PATH_STABLE_SECONDS,
                "pre_mode_ready": False,
                "pre_mode_reason": reason,
                "pre_mode_stable_seconds": 0,
                "post_mode_ready": False,
                "post_mode_reason": "control_path_not_configured",
                "post_mode_stable_seconds": 0,
                "post_mode_required": False,
                "entities": {},
                "read_only": True,
                "service_calls_performed": False,
                "physical_execution_authority": False,
            }

        now = dt_util.now()
        details: dict[str, Any] = {}

        def entity_detail(key: str, entity_id: str) -> dict[str, Any]:
            state = self.hass.states.get(entity_id)
            available = state is not None and state.state not in _UNAVAILABLE_STATES
            stable_s = 0.0
            if available and state is not None:
                stable_s = max(0.0, (now - state.last_changed).total_seconds())
            result = {
                "entity_id": entity_id,
                "available": available,
                "state": None if state is None else state.state,
                "stable_seconds": round(stable_s, 1),
            }
            details[key] = result
            return result

        mode = entity_detail("operating_mode", mode_entity)
        direction = entity_detail("action_direction", direction_entity)
        power = entity_detail("power_setpoint", power_entity)

        pre_blockers: list[str] = []
        if not mode["available"]:
            pre_blockers.append("operating_mode_unavailable")
        elif mode["stable_seconds"] < CONTROL_PATH_STABLE_SECONDS:
            pre_blockers.append("operating_mode_not_stable")
        pre_mode_ready = not pre_blockers
        pre_mode_reason = "pre_mode_ready" if pre_mode_ready else ",".join(pre_blockers)
        pre_mode_stable = mode["stable_seconds"] if mode["available"] else 0.0

        external_active = mode["available"] and mode["state"] == _EXTERNAL_MODE
        post_blockers: list[str] = []
        if not external_active:
            post_mode_ready = False
            post_mode_reason = "awaiting_third_party_control"
            post_mode_stable = 0.0
        else:
            for key, item in (("action_direction", direction), ("power_setpoint", power)):
                if not item["available"]:
                    post_blockers.append(f"{key}_unavailable")
                elif item["stable_seconds"] < CONTROL_PATH_STABLE_SECONDS:
                    post_blockers.append(f"{key}_not_stable")
            post_mode_ready = not post_blockers
            post_mode_reason = "post_mode_ready" if post_mode_ready else ",".join(post_blockers)
            post_mode_stable = (
                min(direction["stable_seconds"], power["stable_seconds"])
                if direction["available"] and power["available"]
                else 0.0
            )

        ready = pre_mode_ready and (post_mode_ready if external_active else True)
        reason = (
            "control_path_ready"
            if ready
            else (post_mode_reason if external_active else pre_mode_reason)
        )
        stable_seconds = post_mode_stable if external_active else pre_mode_stable
        return {
            "configured": True,
            "ready": ready,
            "reason": reason,
            "stable_seconds": round(stable_seconds, 1),
            "required_stable_seconds": CONTROL_PATH_STABLE_SECONDS,
            "pre_mode_ready": pre_mode_ready,
            "pre_mode_reason": pre_mode_reason,
            "pre_mode_stable_seconds": round(pre_mode_stable, 1),
            "post_mode_ready": post_mode_ready,
            "post_mode_reason": post_mode_reason,
            "post_mode_stable_seconds": round(post_mode_stable, 1),
            "post_mode_required": external_active,
            "entities": details,
            "read_only": True,
            "service_calls_performed": False,
            "physical_execution_authority": False,
        }
