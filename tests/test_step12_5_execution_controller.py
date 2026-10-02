from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"

def test_execution_controller_is_source_faithful_physical_controller() -> None:
    text=(INTEGRATION/"ems_execution.py").read_text(encoding="utf-8")
    assert "class DOEMSExecutionController" in text
    assert "async def async_execute_selected_plan" in text
    assert "async def async_execute_automatic_plan" in text
    assert ".services.async_call(" in text
    assert "abs(actual_setpoint - expected_power) > 10" in text

def test_primary_runtime_stop_conditions_match_alpha76() -> None:
    text=(INTEGRATION/"ems_execution.py").read_text(encoding="utf-8")
    for reason in ("planned_energy_reached","target_soc_reached","minimum_soc_reached","device_status_unavailable","battery_power_source_unavailable","max_runtime_reached"):
        assert reason in text

def test_safe_return_and_lifecycle_match_alpha76() -> None:
    text=(INTEGRATION/"ems_execution.py").read_text(encoding="utf-8")
    stop=text[text.index("    async def async_stop("):]
    assert '{"value": 0}' in stop
    assert "await asyncio.sleep(1)" in stop
    assert '{"option": _SELF_MODE}' in stop
    for state in ('"geannuleerd"','"voltooid"','"fout"','"stop_error"'):
        assert state in stop
