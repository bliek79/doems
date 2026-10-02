from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load_gate():
    path = INTEGRATION / "ems_automatic_execution_gate.py"
    spec = importlib.util.spec_from_file_location("ems_automatic_execution_gate_alpha29", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DOEMSAutomaticExecutionGate()


def _ready_data(signature_match: bool) -> dict:
    identity = "laden|veiligheidsladen|2026-10-02T09:30:00+00:00|2026-10-02T10:30:00+00:00"
    detail = {
        "origin": "automatic_72h_planner",
        "lifecycle_status": "pending",
        "planner_identity": identity,
        "planner_signature": identity + "|9.8|0.30",
        "action": "laden",
        "purpose": "veiligheidsladen",
        "power_w": 320,
        "target_soc": 9.8,
        "max_runtime_h": 1.0,
        "price_sources": ["known"],
        "all_prices_known": True,
    }
    return {
        "scheduler_selected_slot": 1,
        "scheduler_ready": True,
        "scheduler_slots": {1: detail},
        "auto_prestart_safe": True,
        "auto_prestart_current_signature_match": signature_match,
        "auto_safety_handoff_safe": True,
        "auto_execution_handoff_ready": True,
        "auto_execution_handoff_planner_identity": identity,
        "auto_final_revalidation_safe": True,
        "auto_final_revalidation_selected_slot": 1,
        "auto_final_revalidation_planner_identity": identity,
        "auto_mode_switch_preview_ready": True,
        "auto_plan_72h_execution_buffer_safe": False,
        "forecast_ready": True,
        "control_path_configured": True,
        "control_path_ready": True,
        "control_path_stable_seconds": 120,
        "control_path_required_stable_seconds": 60,
        "physical_test_active": False,
        "execution_active": False,
        "execution_origin": None,
    }


def test_alpha29_revision_signature_remains_warning_for_stable_identity() -> None:
    gate = _load_gate()
    disarmed = gate.evaluate(_ready_data(False), armed=False)
    assert disarmed["auto_execution_gate_status"] == "ready_disarmed"
    assert disarmed["auto_execution_gate_technical_ready"] is True
    assert disarmed["auto_execution_gate_execution_permitted"] is False
    assert "planner_revision_changed" in disarmed["auto_execution_gate_warnings"]
    assert "planner_revision_changed" not in disarmed["auto_execution_gate_blockers"]

    armed = gate.evaluate(_ready_data(False), armed=True)
    assert armed["auto_execution_gate_status"] == "armed_ready"
    assert armed["auto_execution_gate_execution_permitted"] is True


def test_alpha29_physical_path_does_not_require_rolling_signature_equality() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    physical = (INTEGRATION / "ems_manual_physical_execution.py").read_text(encoding="utf-8")

    assert 'auto_prestart_current_signature_match' not in runtime.split("def _schedule_manual_physical_start", 1)[1].split("async def", 1)[0]
    assert 'snapshot.get("prestart_signature_match") is not True' not in physical
    assert 'live_snapshot.get("prestart_signature_match") is not True' not in physical

    for token in (
        'snapshot.get("auto_execution_gate_status") != "armed_ready"',
        'snapshot.get("auto_execution_gate_execution_permitted") is not True',
        'snapshot.get("auto_execution_gate_selected_slot") != slot',
        'snapshot.get("auto_execution_gate_planner_identity") != planner_identity',
        'live_snapshot.get("auto_execution_gate_planner_identity") != planner_identity',
        'live_snapshot.get("auto_execution_gate_action") != action',
        "Automatic gate-vermogen wijzigde tijdens arming",
        "Automatic gate-doel-SOC wijzigde tijdens arming",
        "Automatic gate-looptijd wijzigde tijdens arming",
    ):
        assert token in physical
