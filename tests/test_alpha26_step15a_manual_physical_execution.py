from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _read(name: str) -> str:
    return (INTEGRATION / name).read_text(encoding="utf-8")


def test_alpha26_step15a_has_one_explicit_manual_physical_executor() -> None:
    physical = _read("ems_manual_physical_execution.py")
    runtime = _read("ems_runtime.py")
    switch = _read("switch.py")

    assert "class DOEMSManualPhysicalExecution" in physical
    assert ".services.async_call(" in physical
    assert '"physical_execution_enabled": True' in switch
    assert '"automatic_planner_execution_enabled": False' in switch
    assert "self.manual_physical_execution = DOEMSManualPhysicalExecution(" in runtime
    assert "self._schedule_manual_physical_start()" in runtime


def test_alpha26_physical_path_is_manual_scheduled_only() -> None:
    physical = _read("ems_manual_physical_execution.py")
    runtime = _read("ems_runtime.py")

    assert "Step 15A staat alleen handmatig geplande acties fysiek toe" in physical
    assert '== "automatic_72h_planner"' in physical
    assert '== "automatic_72h_planner"' in runtime
    assert "scheduler_selected_execution_mode" in runtime
    assert '"gepland"' in runtime
    assert 'detail.get("action") not in {"laden", "ontladen"}' in runtime


def test_alpha26_uses_fixed_physical_handoff_and_safe_return() -> None:
    physical = _read("ems_manual_physical_execution.py")

    assert '_EXTERNAL_MODE = "third_party_control"' in physical
    assert '_SELF_MODE = "self_consumption"' in physical
    assert '"select_option"' in physical
    assert '"set_value"' in physical
    assert '{"value": 0}' in physical
    assert '{"option": _SELF_MODE}' in physical
    assert "step15a_physical_execution_running" in physical
    assert '"actief"' in physical
    assert '"voltooid"' in physical
    assert '"fout"' in physical


def test_alpha26_arm_is_fail_safe_off_and_disarm_stops_physical_run() -> None:
    runtime = _read("ems_runtime.py")
    switch = _read("switch.py")

    assert "self._automatic_execution_armed = False" in runtime
    assert "RestoreEntity" not in switch
    assert "automatic_execution_disarmed" in runtime
    assert "await self.manual_physical_execution.async_stop(" in runtime
    assert "await self.manual_physical_execution.async_shutdown_stop()" in runtime
    assert '"restart_policy": "fail_safe_off_no_resume"' in switch


def test_alpha26_requires_device_status_for_copied_manual_safety_guard() -> None:
    const = _read("const.py")
    flow = _read("config_flow.py")
    runtime = _read("ems_runtime.py")
    safety = _read("ems_safety_guard.py")

    assert 'CONF_DEVICE_STATUS_ENTITY = "device_status_entity"' in const
    assert "CONF_DEVICE_STATUS_ENTITY" in flow
    assert '"device_status": self._read_optional_state(CONF_DEVICE_STATUS_ENTITY)' in runtime
    assert 'data.get("device_status")' in safety


def test_alpha26_automatic_plan72_executor_remains_non_actuating() -> None:
    execution = _read("ems_execution.py")
    gate = _read("ems_automatic_execution_gate.py")

    assert ".services.async_call(" not in execution
    assert '"physical_execution_authority": False' in execution
    assert '"service_calls_performed": False' in execution
    assert ".services.async_call(" not in gate
    assert '"physical_execution_authority": False' in gate
