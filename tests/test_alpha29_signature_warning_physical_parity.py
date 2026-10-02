from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"

def test_identity_remains_leading_and_signature_is_warning_only() -> None:
    execution=(INTEGRATION/"ems_execution.py").read_text(encoding="utf-8")
    assert "planner_identity_match" in execution
    assert 'add_check("planner_signature_match"' in execution
    assert "warning_only=True" in execution
    assert "planner_signature" in execution

def test_alpha76_gate_uses_source_status_names() -> None:
    gate=(INTEGRATION/"ems_automatic_execution_gate.py").read_text(encoding="utf-8")
    for status in ("idle","blocked","ready_disarmed","armed_live_ready"):
        assert f'"{status}"' in gate
    assert '"armed_ready"' not in gate
