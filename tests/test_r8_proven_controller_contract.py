"""Regression guard: R8 observes Alpha76 but must never become a second actuator."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "doems"


def test_r8_supervisor_never_commands_proven_controller():
    source = (ROOT / "execution_runtime.py").read_text()
    assert 'result["proven_execution"]' in source
    assert '"r8_command_issued": False' in source
    assert 'getattr(self.scheduler, "execution", None)' in source
    assert "await proven.async_execute" not in source
    assert "await proven.async_stop" not in source
    assert '"execution_authority": False' in source
    assert '"physical_execution_enabled": False' in source


def test_alpha76_remains_exclusive_physical_owner():
    runtime = (ROOT / "ems_runtime.py").read_text()
    assert "self.execution = DOEMSExecutionController(hass, entry.entry_id)" in runtime
    assert "async_execute_selected_plan_verified_handoff" in runtime
    assert "_async_verify_platform_setpoint_handoff" in runtime
