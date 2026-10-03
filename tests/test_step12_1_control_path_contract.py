from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"
def _read(name:str)->str: return (INTEGRATION/name).read_text(encoding="utf-8")

def test_control_path_observer_remains_read_only_transport_observer() -> None:
    control=_read("ems_control_path.py")
    assert "class DOEMSControlPathObserver" in control
    assert '"read_only": True' in control
    assert ".services.async_call(" not in control

def test_runtime_exposes_control_mapping_to_alpha76_execution() -> None:
    runtime=_read("ems_runtime.py")
    assert "self.control_path = DOEMSControlPathObserver(hass, entry)" in runtime
    assert "self.control_path_result = self.control_path.evaluate()" in runtime
    assert "def control_entity_ids" in runtime
    assert "return dict(self.control_path.entity_ids)" in runtime
    assert '"control_path_configured": bool(control_path.get("configured"))' in runtime
    assert '"operating_mode": control_entities.get("operating_mode", {}).get("state")' in runtime
    assert '"action_direction": control_entities.get("action_direction", {}).get("state")' in runtime
    assert '"power_setpoint_w": control_entities.get("power_setpoint", {}).get("state")' in runtime

def test_physical_test_and_execution_activity_are_live_not_hardcoded_false() -> None:
    runtime=_read("ems_runtime.py")
    assert '"physical_test_active": bool(self.physical_test.data.get("active"))' in runtime
    assert '"execution_active": bool(self.execution.data.get("active"))' in runtime
    assert '"physical_test_active": False' not in runtime
