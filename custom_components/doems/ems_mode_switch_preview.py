"""Step 12.3 guarded mode-switch transaction preview.

The preview mirrors the proven source transaction contract while remaining
strictly non-actuating.
"""
from __future__ import annotations

from typing import Any

_EXTERNAL_MODE = "third_party_control"
_SELF_MODE = "self_consumption"
_DIRECTION = {"laden": "charge", "ontladen": "discharge"}


def _number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class DOEMSModeSwitchPreview:
    """Build a read-only transaction plan after final revalidation."""

    def evaluate(self, data: dict[str, Any]) -> dict[str, Any]:
        required = bool(data.get("auto_final_revalidation_required"))
        safe = data.get("auto_final_revalidation_safe") is True
        mode = data.get("operating_mode")
        action = data.get("auto_final_revalidation_action")
        power = _number(data.get("auto_final_revalidation_power_w"))
        direction = _DIRECTION.get(str(action))
        control_entities = data.get("control_path_entities") or {}
        mode_entity = (control_entities.get("operating_mode") or {}).get("entity_id")
        direction_entity = (control_entities.get("action_direction") or {}).get("entity_id")
        power_entity = (control_entities.get("power_setpoint") or {}).get("entity_id")
        required_stable = float(data.get("control_path_required_stable_seconds") or 60)
        pre_stable = float(data.get("control_path_pre_mode_stable_seconds") or 0)
        post_ready = data.get("control_path_post_mode_ready") is True

        blockers: list[str] = []
        if required and not safe:
            blockers.append("final_revalidation_not_ready")
        if required and not data.get("control_path_configured"):
            blockers.append("control_path_not_configured")
        if required and mode not in {_SELF_MODE, _EXTERNAL_MODE}:
            blockers.append("operating_mode_invalid")
        if required and data.get("control_path_pre_mode_ready") is not True:
            blockers.append("operating_mode_not_stable")
        if required and pre_stable < required_stable:
            blockers.append("operating_mode_not_stable")
        if required and action not in _DIRECTION:
            blockers.append("invalid_action")
        if required and direction is None:
            blockers.append("invalid_direction_mapping")
        max_power = int(data.get("max_discharge_power_w") or 800) if action == "ontladen" else int(data.get("max_charge_power_w") or 800)
        if required and (power is None or not 100 <= power <= max_power):
            blockers.append("invalid_power")
        if required and not mode_entity:
            blockers.append("operating_mode_unavailable")
        if required and not direction_entity:
            blockers.append("direction_entity_unavailable")
        if required and not power_entity:
            blockers.append("power_setpoint_entity_unavailable")
        if required and mode == _EXTERNAL_MODE and not post_ready:
            blockers.append("post_mode_not_ready")
        if required and data.get("physical_test_active"):
            blockers.append("physical_test_active")
        if required and data.get("execution_active"):
            blockers.append("execution_controller_busy")

        blockers = list(dict.fromkeys(blockers))
        ready = required and safe and not blockers
        switch_required = ready and mode != _EXTERNAL_MODE
        already_external = ready and mode == _EXTERNAL_MODE

        if not required:
            status = "not_required"
        elif blockers:
            status = "blocked"
        elif switch_required:
            status = "switch_required"
        elif already_external:
            status = "already_external"
        else:
            status = "blocked"

        zero_power_guard_required = True
        transaction = [
            {"sequence": 1, "operation": "revalidate", "target": "final_revalidation", "expected": "ready", "physical": False},
            {"sequence": 2, "operation": "set_zero_power_guard", "entity": power_entity, "value": 0, "physical": False},
            {"sequence": 3, "operation": "select_option", "entity": mode_entity, "value": _EXTERNAL_MODE, "required": mode != _EXTERNAL_MODE, "physical": False},
            {"sequence": 4, "operation": "verify_state", "entity": mode_entity, "expected": _EXTERNAL_MODE, "physical": False},
            {"sequence": 5, "operation": "wait_stable", "seconds": int(required_stable), "physical": False},
            {"sequence": 6, "operation": "post_mode_revalidation", "expected": "ready", "physical": False},
            {"sequence": 7, "operation": "select_option", "entity": direction_entity, "value": direction, "physical": False},
            {"sequence": 8, "operation": "verify_state", "entity": direction_entity, "expected": direction, "physical": False},
            {"sequence": 9, "operation": "set_value", "entity": power_entity, "value": int(power) if power is not None else None, "physical": False},
            {"sequence": 10, "operation": "verify_value", "entity": power_entity, "expected": int(power) if power is not None else None, "physical": False},
            {"sequence": 11, "operation": "release_execution_controller", "expected": "ready", "physical": False},
            {"sequence": 12, "operation": "safe_return_self_consumption", "entity": mode_entity, "value": _SELF_MODE, "physical": False},
        ]

        return {
            "auto_mode_switch_preview_enabled": True,
            "auto_mode_switch_preview_required": required,
            "auto_mode_switch_preview_ready": ready,
            "auto_mode_switch_preview_status": status,
            "auto_mode_switch_preview_reason": (
                "Guarded mode-switchtransactie is preview-gereed; geen fysieke writes toegestaan"
                if ready else (", ".join(blockers) if blockers else "Geen finale revalidatie actief")
            ),
            "auto_mode_switch_preview_blockers": blockers,
            "auto_mode_switch_preview_current_mode": mode,
            "auto_mode_switch_preview_target_mode": _EXTERNAL_MODE,
            "auto_mode_switch_preview_switch_required": switch_required,
            "auto_mode_switch_preview_already_external": already_external,
            "auto_mode_switch_preview_action": action,
            "auto_mode_switch_preview_direction": direction,
            "auto_mode_switch_preview_requested_power_w": int(power) if power is not None else None,
            "auto_mode_switch_preview_zero_power_guard_required": zero_power_guard_required,
            "auto_mode_switch_preview_post_mode_revalidation_required": True,
            "auto_mode_switch_preview_safe_return_required": True,
            "auto_mode_switch_preview_transaction": transaction,
            "auto_mode_switch_preview_preview_only": True,
            "auto_mode_switch_preview_transaction_started": False,
            "auto_mode_switch_preview_mode_switch_performed": False,
            "auto_mode_switch_preview_direction_written": False,
            "auto_mode_switch_preview_power_setpoint_written": False,
            "auto_mode_switch_preview_execution_controller_released": False,
            "auto_mode_switch_preview_execution_permitted": False,
            "auto_mode_switch_preview_physical_control": False,
            "automatic_execution_armed": False,
            "service_calls_performed": False,
            "physical_execution_authority": False,
        }
