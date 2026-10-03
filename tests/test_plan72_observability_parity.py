from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"

def test_plan72_observability_surface_remains_read_only() -> None:
    sensor=(INTEGRATION/"sensor.py").read_text(encoding="utf-8")
    assert "class DOEMSEMSPlan72Sensor" in sensor
    assert ".services.async_call(" not in sensor
    assert 'attrs["plan"] = data.get("auto_plan_72h_plan", [])' in sensor
    assert '_unrecorded_attributes = frozenset({"plan"})' in sensor

def test_physical_authority_is_confined_to_execution_and_physical_test_controllers() -> None:
    execution=(INTEGRATION/"ems_execution.py").read_text(encoding="utf-8")
    physical=(INTEGRATION/"ems_physical_test.py").read_text(encoding="utf-8")
    assert ".services.async_call(" in execution
    assert ".services.async_call(" in physical
    for name in ("ems_planner_bridge.py","ems_scheduler.py","ems_prestart_validator.py","ems_safety_guard.py","ems_action_controller.py","ems_automatic_execution_gate.py"):
        assert ".services.async_call(" not in (INTEGRATION/name).read_text(encoding="utf-8")

def test_plan72_planner_itself_remains_non_actuating() -> None:
    planner=(INTEGRATION/"ems_alpha76"/"planner_72h.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in planner
    assert "select_option" not in planner
    assert "set_value" not in planner
