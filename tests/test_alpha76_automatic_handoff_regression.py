"""Regression checks for the existing Alpha76 automatic execution handoff.

The R7 automatic path must verify host setpoint acceptance just like the
manual path, and must stop through the one proven Alpha76 controller on error.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "doems"


def test_automatic_execution_uses_existing_verified_handoff():
    runtime = (ROOT / "ems_runtime.py").read_text()
    start = runtime.index("async def _run_automatic()")
    end = runtime.index("self._automatic_execution_task = self.hass.async_create_task", start)
    path = runtime[start:end]
    assert "await self.execution.async_execute_automatic_plan(str(identity))" in path
    assert "if started:" in path
    assert "await self._async_verify_platform_setpoint_handoff(" in path
    assert 'execution_state.get("power_w")' in path
    assert 'await self.execution.async_stop(reason, emergency=True)' in path
    assert 'await self.execution.async_stop(' in path


def test_only_alpha76_execution_is_registered_on_startup():
    startup = (ROOT / "__init__.py").read_text()
    assert "DOEMSEMSRuntime(" in startup
    assert "await ems_runtime.async_setup()" in startup
    assert "DOEMSExecutionSupervisor(" not in startup
    assert '"r8_supervisor"' not in startup
    runtime = (ROOT / "ems_runtime.py").read_text()
    assert "self.execution = DOEMSExecutionController(hass, entry.entry_id)" in runtime
