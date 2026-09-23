from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _read(name: str) -> str:
    return (INTEGRATION / name).read_text(encoding="utf-8")


def _load_gate():
    path = INTEGRATION / "ems_automatic_execution_gate.py"
    spec = importlib.util.spec_from_file_location("ems_automatic_execution_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DOEMSAutomaticExecutionGate()


def _ready_data(*, purpose: str = "veiligheidsladen", all_prices_known: bool = False) -> dict:
    identity = "laden|veiligheidsladen|2026-09-23T12:00:00+00:00|2026-09-23T13:00:00+00:00"
    detail = {
        "origin": "automatic_72h_planner",
        "lifecycle_status": "pending",
        "planner_identity": identity,
        "planner_signature": identity + "|77.1|0.17",
        "action": "laden",
        "purpose": purpose,
        "power_w": 180,
        "target_soc": 77.1,
        "max_runtime_h": 1,
        "price_sources": ["known"] if all_prices_known else ["forecast"],
        "all_prices_known": all_prices_known,
    }
    return {
        "scheduler_selected_slot": 1,
        "scheduler_ready": True,
        "scheduler_slots": {1: detail},
        "auto_prestart_safe": True,
        "auto_prestart_current_signature_match": True,
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
        "physical_test_active": False,
        "execution_active": False,
        "execution_origin": None,
    }


def test_step12_4_idle_is_not_execution_permitted() -> None:
    gate = _load_gate()
    result = gate.evaluate(
        {
            "scheduler_selected_slot": None,
            "scheduler_ready": False,
            "scheduler_slots": {},
            "execution_active": False,
        },
        armed=True,
    )
    assert result["auto_execution_gate_status"] == "idle"
    assert result["auto_execution_gate_technical_ready"] is False
    assert result["auto_execution_gate_execution_permitted"] is False
    assert result["physical_execution_authority"] is False


def test_step12_4_ready_disarmed_then_armed_ready() -> None:
    gate = _load_gate()
    data = _ready_data()
    disarmed = gate.evaluate(data, armed=False)
    assert disarmed["auto_execution_gate_status"] == "ready_disarmed"
    assert disarmed["auto_execution_gate_technical_ready"] is True
    assert disarmed["auto_execution_gate_execution_permitted"] is False
    assert disarmed["auto_execution_gate_safety_recovery_exception"] is True

    armed = gate.evaluate(data, armed=True)
    assert armed["auto_execution_gate_status"] == "armed_ready"
    assert armed["auto_execution_gate_technical_ready"] is True
    assert armed["auto_execution_gate_execution_permitted"] is True
    assert armed["execution_controller_invoked"] is False
    assert armed["service_calls_performed"] is False
    assert armed["physical_execution_authority"] is False


def test_step12_4_signature_is_warning_identity_change_is_blocker() -> None:
    gate = _load_gate()
    data = _ready_data()
    data["auto_prestart_current_signature_match"] = False
    warned = gate.evaluate(data, armed=False)
    assert warned["auto_execution_gate_technical_ready"] is True
    assert "planner_revision_changed" in warned["auto_execution_gate_warnings"]

    data["auto_final_revalidation_planner_identity"] = "different"
    blocked = gate.evaluate(data, armed=True)
    assert blocked["auto_execution_gate_status"] == "blocked"
    assert "planner_identity_changed" in blocked["auto_execution_gate_blockers"]
    assert blocked["auto_execution_gate_execution_permitted"] is False


def test_step12_4_manual_override_blocks() -> None:
    gate = _load_gate()
    result = gate.evaluate(
        {
            "scheduler_selected_slot": 1,
            "scheduler_ready": True,
            "scheduler_slots": {
                1: {
                    "origin": "manual",
                    "action": "laden",
                    "purpose": None,
                }
            },
            "execution_active": False,
        },
        armed=True,
    )
    assert result["auto_execution_gate_status"] == "blocked"
    assert "manual_override_active" in result["auto_execution_gate_blockers"]
    assert result["auto_execution_gate_execution_permitted"] is False


def test_step12_4_trade_requires_known_prices() -> None:
    gate = _load_gate()
    data = _ready_data(purpose="handelsladen", all_prices_known=False)
    data["auto_plan_72h_execution_buffer_safe"] = True
    blocked = gate.evaluate(data, armed=True)
    assert "trade_requires_known_prices" in blocked["auto_execution_gate_blockers"]
    assert blocked["auto_execution_gate_execution_permitted"] is False

    known = _ready_data(purpose="handelsladen", all_prices_known=True)
    known["auto_plan_72h_execution_buffer_safe"] = True
    ready = gate.evaluate(known, armed=True)
    assert ready["auto_execution_gate_status"] == "armed_ready"
    assert ready["auto_execution_gate_execution_permitted"] is True


def test_step12_4_normal_action_cannot_bypass_unsafe_buffer() -> None:
    gate = _load_gate()
    data = _ready_data(purpose="laden_voor_verbruik")
    blocked = gate.evaluate(data, armed=True)
    assert "execution_buffer_unsafe" in blocked["auto_execution_gate_blockers"]

    recovery = gate.evaluate(_ready_data(purpose="veiligheidsladen"), armed=True)
    assert "execution_buffer_unsafe" not in recovery["auto_execution_gate_blockers"]


def test_step12_4_control_path_and_runtime_blockers() -> None:
    gate = _load_gate()
    data = _ready_data()
    data["control_path_ready"] = False
    data["physical_test_active"] = True
    data["execution_active"] = True
    data["execution_origin"] = "manual"
    result = gate.evaluate(data, armed=True)
    for blocker in (
        "control_path_not_stable",
        "physical_test_active",
        "execution_already_active",
        "manual_override_active",
    ):
        assert blocker in result["auto_execution_gate_blockers"]
    assert result["auto_execution_gate_execution_permitted"] is False


def test_step12_4_source_is_non_actuating_and_switch_is_fail_safe_off() -> None:
    gate_text = _read("ems_automatic_execution_gate.py")
    runtime_text = _read("ems_runtime.py")
    switch_text = _read("switch.py")

    assert ".services.async_call(" not in gate_text
    assert '"execution_controller_invoked": False' in gate_text
    assert '"service_calls_performed": False' in gate_text
    assert '"physical_execution_authority": False' in gate_text

    assert "self._automatic_execution_armed = False" in runtime_text
    assert "RestoreEntity" not in switch_text
    assert '"physical_execution_enabled": False' in switch_text
    assert '"restart_policy": "fail_safe_off"' in switch_text
    assert "async_set_automatic_execution_armed(True)" in switch_text
    assert "async_set_automatic_execution_armed(False)" in switch_text


def test_step12_4_runtime_stops_before_step12_5() -> None:
    runtime = _read("ems_runtime.py")
    assert '"execution_controller_invoked": False' in runtime
    assert '"service_calls_performed": False' in runtime
    assert '"physical_execution_authority": False' in runtime
    assert "async_execute_selected_plan" not in runtime
