from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"
def _read(name: str)->str: return (INTEGRATION/name).read_text(encoding="utf-8")

def test_source_execution_replaces_step15a_writer() -> None:
    runtime=_read("ems_runtime.py"); execution=_read("ems_execution.py")
    assert "self.execution = DOEMSExecutionController(hass, entry.entry_id)" in runtime
    assert "DOEMSManualPhysicalExecution" not in runtime
    assert ".services.async_call(" in execution

def test_manual_scheduled_execution_is_independent_of_automatic_arm() -> None:
    runtime=_read("ems_runtime.py")
    start=runtime.index("    def _schedule_manual_physical_start")
    end=runtime.index("    @property\n    def control_entity_ids",start)
    manual=runtime[start:end]
    manual=manual[manual.index('        if origin != "manual":'):]
    assert "_automatic_execution_armed" not in manual
    assert "await self.async_execute_selected_plan_verified_handoff()" in manual
    assert "platform_setpoint_handoff_not_confirmed" in manual
    assert "retry_wait:" in manual

def test_alpha76_safe_return_is_fixed_zero_wait_self_consumption() -> None:
    execution=_read("ems_execution.py")
    stop=execution[execution.index("    async def async_stop("):]
    assert '{"value": 0}' in stop
    assert "await asyncio.sleep(1)" in stop
    assert '{"option": _SELF_MODE}' in stop

def test_alpha76_arm_restores_live_guarded_state() -> None:
    switch=_read("switch.py")
    assert "RestoreEntity" in switch
    assert 'previous.state == "on"' in switch
    assert 'previous.attributes.get("mode") == "live_guarded"' in switch
