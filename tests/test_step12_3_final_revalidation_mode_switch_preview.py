from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"

def test_runtime_uses_alpha76_execution_owned_revalidation() -> None:
    runtime=(INTEGRATION/"ems_runtime.py").read_text(encoding="utf-8")
    assert "self.execution.evaluate_automatic_handoff(" in runtime
    assert "self.execution.evaluate_final_revalidation(" in runtime
    assert "self.execution.evaluate_mode_switch_transaction(" in runtime
    assert "self.final_revalidation =" not in runtime
    assert "self.mode_switch_preview =" not in runtime

def test_source_final_revalidation_and_mode_preview_are_present() -> None:
    execution=(INTEGRATION/"ems_execution.py").read_text(encoding="utf-8")
    assert "def evaluate_final_revalidation(" in execution
    assert "def evaluate_mode_switch_transaction(" in execution
    assert '"auto_final_revalidation_safe"' in execution
    assert '"auto_mode_switch_preview_ready"' in execution
