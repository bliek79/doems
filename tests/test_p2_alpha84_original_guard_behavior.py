"""Behavioral P2 comparison using original frozen Alpha84 Safety Guard code.

Do not use a fake guard in these tests: extract and execute the actual
unmodified Alpha84 class from the reference source, with its constant
bounds. No Home Assistant commands or physical authorizations.
"""
import ast
from pathlib import Path
from typing import Any
from custom_components.doems.alpha84_handoff_contract import project_combined_slot

SOURCE = Path(__file__).resolve().parents[1] / "reference/anker_ems_alpha84/safety_guard.py"


def original_guard():
    tree = ast.parse(SOURCE.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AnkerEmsSafetyGuard")
    isolated = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(isolated)
    context = {"Any": Any, "MIN_SOC_PERCENT": 5, "MAX_SOC_PERCENT": 100}
    exec(compile(isolated, str(SOURCE), "exec"), context)
    return context["AnkerEmsSafetyGuard"]()


def plan(power=500, action="laden"):
    decision = {"selected_slot": 1, "selected_lifecycle": "pending",
                "selected_action": action, "safety_status": "safe", "safety_blockers": []}
    slot = {"lifecycle_status": "pending", "origin": "automatic",
            "planner_identity": "same-plan", "planner_signature": "same-revision",
            "action": action, "power_w": power, "target_soc": 85,
            "max_runtime_h": 1.0}
    return project_combined_slot(decision, slot, sources_fresh=True, safety_safe=True)


def evidence(projected):
    return {
        **projected, "soc": 40, "charge_power_w": 0, "discharge_power_w": 0,
        "max_charge_power_w": 800, "max_discharge_power_w": 800,
        "auto_prestart_required": True, "auto_prestart_safe": True,
        "auto_prestart_current_identity_match": True,
        "auto_prestart_current_signature_match": True,
        "auto_bridge_valid": True, "forecast_ready": True,
        "auto_plan_72h_execution_buffer_safe": True,
        "control_path_configured": True, "physical_test_active": False,
        "execution_active": False,
    }


def test_original_alpha84_handoff_accepts_projected_doems_plan():
    result = original_guard().evaluate_automatic_handoff(evidence(plan()))
    assert result["auto_safety_handoff_safe"] is True
    assert result["auto_safety_handoff_planner_identity"] == "same-plan"
    assert result["auto_safety_handoff_execution_permitted"] is False


def test_original_alpha84_guard_blocks_power_above_legacy_limit():
    result = original_guard().evaluate_automatic_handoff(evidence(plan(power=900)))
    assert result["auto_safety_handoff_safe"] is False
    assert "invalid_power" in result["auto_safety_handoff_reasons"]


def test_original_alpha84_guard_blocks_missing_prestart_proof():
    data = evidence(plan())
    data["auto_prestart_safe"] = False
    result = original_guard().evaluate_automatic_handoff(data)
    assert result["auto_safety_handoff_safe"] is False
    assert "prestart_not_safe" in result["auto_safety_handoff_reasons"]


def test_original_alpha84_guard_blocks_missing_identity_confirmation():
    data = evidence(plan())
    data["auto_prestart_current_identity_match"] = False
    result = original_guard().evaluate_automatic_handoff(data)
    assert result["auto_safety_handoff_safe"] is False
    assert "planner_identity_mismatch" in result["auto_safety_handoff_reasons"]


def test_original_alpha84_guard_blocks_active_physical_test():
    data = evidence(plan())
    data["physical_test_active"] = True
    result = original_guard().evaluate_automatic_handoff(data)
    assert result["auto_safety_handoff_safe"] is False
    assert "physical_test_active" in result["auto_safety_handoff_reasons"]
