from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"
def _read(name: str)->str: return (INTEGRATION/name).read_text(encoding="utf-8")

def test_automatic_plan72_uses_alpha76_execution_controller() -> None:
    execution=_read("ems_execution.py"); runtime=_read("ems_runtime.py")
    assert "async def async_execute_automatic_plan" in execution
    assert "await self.execution.async_execute_automatic_plan(str(identity))" in runtime
    assert "DOEMSManualPhysicalExecution" not in runtime

def test_alpha76_execution_revalidates_after_external_mode_switch() -> None:
    execution=_read("ems_execution.py")
    assert "_wait_for_external_controls" in execution
    assert "evaluate_final_revalidation" in execution
    assert "evaluate_mode_switch_transaction" in execution
    assert "automatic_start_failed" in execution

def test_manual_priority_is_preserved_by_gate() -> None:
    gate=_read("ems_automatic_execution_gate.py")
    assert "manual_override_active" in gate
    assert 'origin != "automatic_72h_planner"' in gate

def test_automatic_arm_is_restoreentity_live_guarded() -> None:
    switch=_read("switch.py")
    assert "RestoreEntity" in switch
    assert '"mode": "live_guarded"' in switch
    assert "automatic_execution_disarmed" in switch
