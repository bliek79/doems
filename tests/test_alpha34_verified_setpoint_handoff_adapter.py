from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _read(name: str) -> str:
    return (INTEGRATION / name).read_text(encoding="utf-8")


def _blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def test_alpha34_is_host_adapter_not_alpha76_execution_change() -> None:
    assert _blob_sha(INTEGRATION / "ems_execution.py") == "82079d53144eb2cc52abd3f1e2e857f7a6fb7812"
    runtime = _read("ems_runtime.py")
    assert "alpha34_verified_physical_setpoint_handoff_v1" in runtime
    assert "_PLATFORM_SETPOINT_HANDOFF_TOLERANCE_W = 10.0" in runtime


def test_verified_handoff_delegates_to_frozen_execution_then_checks_host_state() -> None:
    runtime = _read("ems_runtime.py")
    start = runtime.index("    async def async_execute_selected_plan_verified_handoff")
    end = runtime.index("    def _schedule_manual_physical_start", start)
    block = runtime[start:end]
    assert "await self.execution.async_execute_selected_plan()" in block
    assert "await self._async_verify_platform_setpoint_handoff(expected_power_w)" in block
    assert 'await self.execution.async_stop(reason, emergency=True)' in block
    assert "platform_setpoint_handoff_not_confirmed" in block


def test_manual_scheduled_retry_uses_verified_handoff_without_automatic_arm() -> None:
    runtime = _read("ems_runtime.py")
    start = runtime.index("    def _schedule_manual_physical_start")
    end = runtime.index("    @property\n    def control_entity_ids", start)
    block = runtime[start:end]
    manual = block[block.index('        if origin != "manual":'):]
    assert "_automatic_execution_armed" not in manual
    assert "await self.async_execute_selected_plan_verified_handoff()" in manual
    assert '"platform_setpoint_handoff_not_confirmed"' in manual
    assert "retry_wait:" in manual


def test_direct_manual_services_use_same_host_adapter() -> None:
    init = _read("__init__.py")
    assert init.count("await runtime.async_execute_selected_plan_verified_handoff()") >= 2


def test_source_monitor_tolerance_remains_frozen() -> None:
    execution = _read("ems_execution.py")
    assert "abs(actual_setpoint - expected_power) > 10" in execution
    assert 'await self.async_stop("power_setpoint_changed", emergency=True)' in execution
