from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"

def test_interrupted_execution_is_safe_stopped_on_restart() -> None:
    execution=(INTEGRATION/"ems_execution.py").read_text(encoding="utf-8")
    runtime=(INTEGRATION/"ems_runtime.py").read_text(encoding="utf-8")
    assert 'await self.async_stop("restart_recovery", emergency=True)' in execution
    assert "await self.execution.async_recover_if_needed()" in runtime

def test_automatic_arm_restore_is_separate_from_execution_recovery() -> None:
    switch=(INTEGRATION/"switch.py").read_text(encoding="utf-8")
    runtime=(INTEGRATION/"ems_runtime.py").read_text(encoding="utf-8")
    assert "RestoreEntity" in switch
    assert 'previous.attributes.get("mode") == "live_guarded"' in switch
    assert "self._automatic_execution_armed = False" in runtime
    assert "fail_safe_off_no_resume" not in switch

def test_source_native_execution_store_replaces_old_preview_persistence() -> None:
    execution=(INTEGRATION/"ems_execution.py").read_text(encoding="utf-8")
    runtime=(INTEGRATION/"ems_runtime.py").read_text(encoding="utf-8")
    assert "Store[dict[str, Any]]" in execution
    assert "async def async_load(self)" in execution
    assert "restore_persistence(" not in runtime
    assert "export_persistence(" not in runtime
