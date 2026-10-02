from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _read(name: str) -> str:
    return (INTEGRATION / name).read_text(encoding="utf-8")


def test_alpha27_opens_only_guarded_automatic_plan72_on_proven_writer() -> None:
    physical = _read("ems_manual_physical_execution.py")
    runtime = _read("ems_runtime.py")
    switch = _read("switch.py")

    assert "class DOEMSManualPhysicalExecution" in physical
    assert 'origin == "automatic_72h_planner"' in physical
    assert 'snapshot.get("auto_execution_gate_status") != "armed_ready"' in physical
    assert 'snapshot.get("auto_execution_gate_execution_permitted") is not True' in physical
    assert 'snapshot.get("auto_execution_gate_selected_slot") != slot' in physical
    assert 'snapshot.get("auto_execution_gate_planner_identity") != planner_identity' in physical
    assert 'snapshot.get("prestart_signature_match") is not True' not in physical
    assert 'origin == "automatic_72h_planner"' in runtime
    assert 'gate.get("auto_execution_gate_status") != "armed_ready"' in runtime
    assert 'gate.get("auto_execution_gate_execution_permitted") is not True' in runtime
    assert '"automatic_planner_execution_enabled": True' in switch


def test_alpha27_keeps_exact_physical_transaction_and_safe_return() -> None:
    physical = _read("ems_manual_physical_execution.py")

    assert '_EXTERNAL_MODE = "third_party_control"' in physical
    assert '_SELF_MODE = "self_consumption"' in physical
    assert '{"value": 0}' in physical
    assert '{"option": _SELF_MODE}' in physical
    assert '"charge" if action == "laden" else "discharge"' in physical
    assert "unexpected_discharge" in physical
    assert "unexpected_charge" in physical
    assert "operating_mode_changed" in physical
    assert "direction_changed" in physical
    assert "power_setpoint_changed" in physical
    assert '"safe_return_performed": not errors' in physical


def test_alpha27_revalidates_automatic_identity_after_mode_switch() -> None:
    physical = _read("ems_manual_physical_execution.py")

    assert 'await refresh("physical_post_mode_revalidation")' in physical
    assert 'live_snapshot.get("auto_execution_gate_status") != "armed_ready"' in physical
    assert 'live_snapshot.get("auto_execution_gate_execution_permitted") is not True' in physical
    assert 'live_snapshot.get("auto_execution_gate_selected_slot") != slot' in physical
    assert 'live_snapshot.get("auto_execution_gate_planner_identity") != planner_identity' in physical
    assert 'live_snapshot.get("prestart_signature_match") is not True' not in physical
    assert 'live_snapshot.get("auto_execution_gate_action") != action' in physical
    assert "Automatic gate-vermogen wijzigde tijdens arming" in physical
    assert "Automatic gate-doel-SOC wijzigde tijdens arming" in physical
    assert "Automatic gate-looptijd wijzigde tijdens arming" in physical


def test_alpha27_manual_priority_and_shadow_gate_boundaries_remain() -> None:
    gate = _read("ems_automatic_execution_gate.py")
    execution = _read("ems_execution.py")

    assert '"manual_override_active"' in gate
    assert '"automatic_72h_planner"' in gate
    assert ".services.async_call(" not in gate
    assert ".services.async_call(" not in execution
    assert '"physical_execution_authority": False' in gate
    assert '"physical_execution_authority": False' in execution


def test_alpha27_arm_remains_fail_safe_off_no_resume() -> None:
    runtime = _read("ems_runtime.py")
    switch = _read("switch.py")

    assert "self._automatic_execution_armed = False" in runtime
    assert "RestoreEntity" not in switch
    assert '"restart_policy": "fail_safe_off_no_resume"' in switch
    assert "await self.manual_physical_execution.async_shutdown_stop()" in runtime


def test_alpha27_publishes_phase2_execution_observability() -> None:
    runtime = _read("ems_runtime.py")
    switch = _read("switch.py")

    for token in (
        '"physical_execution_origin"',
        '"physical_execution_planner_identity"',
        '"physical_execution_planner_signature"',
        '"physical_execution_status"',
        '"physical_execution_action"',
        '"physical_execution_power_w"',
        '"physical_execution_safe_return_performed"',
        '"automatic_planner_physical_execution_enabled": True',
    ):
        assert token in runtime

    assert '"selected_origin": data.get("physical_execution_origin")' in switch
    assert '"physical_execution_status": data.get("physical_execution_status")' in switch
    assert '"physical_execution_safe_return_performed"' in switch
