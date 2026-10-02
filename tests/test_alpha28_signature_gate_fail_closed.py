from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load_gate():
    path = INTEGRATION / "ems_automatic_execution_gate.py"
    spec = importlib.util.spec_from_file_location("ems_automatic_execution_gate_alpha28", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DOEMSAutomaticExecutionGate()


def _ready_data(signature_match: bool) -> dict:
    identity = "laden|veiligheidsladen|2026-10-02T08:15:00+00:00|2026-10-02T09:15:00+00:00"
    detail = {
        "origin": "automatic_72h_planner",
        "lifecycle_status": "pending",
        "planner_identity": identity,
        "planner_signature": identity + "|8.1|0.17",
        "action": "laden",
        "purpose": "veiligheidsladen",
        "power_w": 180,
        "target_soc": 8.1,
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


def test_alpha28_signature_revision_blocks_disarmed_gate() -> None:
    result = _load_gate().evaluate(_ready_data(False), armed=False)
    assert result["auto_execution_gate_status"] == "blocked"
    assert result["auto_execution_gate_technical_ready"] is False
    assert result["auto_execution_gate_execution_permitted"] is False
    assert "planner_revision_changed" in result["auto_execution_gate_blockers"]
    assert "planner_revision_changed" not in result["auto_execution_gate_warnings"]


def test_alpha28_signature_revision_blocks_even_when_user_armed() -> None:
    result = _load_gate().evaluate(_ready_data(False), armed=True)
    assert result["auto_execution_gate_status"] == "blocked"
    assert result["auto_execution_gate_technical_ready"] is False
    assert result["auto_execution_gate_execution_permitted"] is False


def test_alpha28_matching_signature_preserves_phase2_ready_states() -> None:
    gate = _load_gate()
    disarmed = gate.evaluate(_ready_data(True), armed=False)
    assert disarmed["auto_execution_gate_status"] == "ready_disarmed"
    assert disarmed["auto_execution_gate_technical_ready"] is True
    assert disarmed["auto_execution_gate_execution_permitted"] is False

    armed = gate.evaluate(_ready_data(True), armed=True)
    assert armed["auto_execution_gate_status"] == "armed_ready"
    assert armed["auto_execution_gate_technical_ready"] is True
    assert armed["auto_execution_gate_execution_permitted"] is True


def test_alpha28_keeps_runtime_and_physical_signature_fences() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    physical = (INTEGRATION / "ems_manual_physical_execution.py").read_text(encoding="utf-8")

    assert 'auto_prestart_current_signature_match' in runtime
    assert 'prestart_signature_match' in physical
    assert 'Automatic planner_signature is niet actueel/stabiel' in physical
