from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"

def _read(name: str) -> str:
    return (INTEGRATION/name).read_text(encoding="utf-8")

def test_old_non_actuating_execution_contract_is_superseded_by_alpha76_copy() -> None:
    execution=_read("ems_execution.py"); runtime=_read("ems_runtime.py")
    assert "class DOEMSExecutionController" in execution
    assert ".services.async_call(" in execution
    assert "async def async_execute_selected_plan" in execution
    assert "async def async_execute_automatic_plan" in execution
    assert "DOEMSManualPhysicalExecution" not in runtime

def test_execution_persistence_is_source_native_store() -> None:
    execution=_read("ems_execution.py"); runtime=_read("ems_runtime.py")
    assert "Store[dict[str, Any]]" in execution
    assert "async def async_load(self)" in execution
    assert "async def _async_save(self)" in execution
    assert "restore_persistence(" not in runtime
    assert "export_persistence(" not in runtime
