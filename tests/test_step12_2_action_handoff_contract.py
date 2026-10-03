from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"
def _read(name:str)->str: return (INTEGRATION/name).read_text(encoding="utf-8")

def test_action_controller_remains_source_translated_and_non_actuating() -> None:
    action=_read("ems_action_controller.py")
    assert "class DOEMSActionController" in action
    assert ".services.async_call(" not in action
    assert '"controller_physical_control": False' in action

def test_execution_handoff_is_owned_by_alpha76_execution_controller() -> None:
    runtime=_read("ems_runtime.py")
    execution=_read("ems_execution.py")
    assert "self.execution.evaluate_automatic_handoff(" in runtime
    assert "def evaluate_automatic_handoff(" in execution
    assert "self.execution_handoff =" not in runtime

def test_runtime_keeps_manual_and_automatic_execution_paths_separate() -> None:
    runtime=_read("ems_runtime.py")
    assert 'if origin == "automatic_72h_planner":' in runtime
    assert 'if origin != "manual":' in runtime
    assert "await self.execution.async_execute_automatic_plan(str(identity))" in runtime
    assert "await self.execution.async_execute_selected_plan()" in runtime

def test_execution_diagnostics_report_live_source_controller_state() -> None:
    runtime=_read("ems_runtime.py")
    assert '"execution_handoff_invoked": bool(execution_handoff)' in runtime
    assert '"execution_handoff_status": execution_handoff.get(' in runtime
    assert '"execution_handoff_ready": execution_handoff.get(' in runtime
    assert '"physical_execution_authority": bool(' in runtime
