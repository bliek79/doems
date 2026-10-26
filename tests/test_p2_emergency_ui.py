"""P2 approved UI names and fail-closed acknowledgement integration contracts."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "doems"


def source(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_emergency_platform_registered():
    const = source("const.py")
    assert '"button"' in const.split("PLATFORMS =", 1)[1].split("\n", 1)[0]
    assert "async_forward_entry_setups(" in source("__init__.py")


def test_approved_button_name_and_central_service():
    code = source("button.py")
    ast.parse(code)
    assert '_attr_name = "DOEMS EMS noodstop bevestigen"' in code
    assert '_attr_unique_id = "doems_ems_emergency_acknowledge"' in code
    assert '_attr_suggested_object_id = "doems_ems_emergency_acknowledge"' in code
    assert 'DOMAIN, "reset_emergency_status", {}, blocking=True' in code
    assert "number.set_value" not in code
    assert "select.select_option" not in code


def test_approved_emergency_sensor_is_registered_and_non_actuating():
    code = source("sensor.py")
    ast.parse(code)
    assert "DOEMSEmergencyStatusSensor(entry, combined_execution)" in code
    assert '_attr_name = "DOEMS EMS noodstopstatus"' in code
    assert '_attr_unique_id = "doems_ems_emergency_status"' in code
    assert '_attr_suggested_object_id = "doems_ems_emergency_status"' in code
    assert '"reset_safety_sources_verified": False' in code


def test_service_stays_fail_closed_without_verified_safety_sources():
    code = source("__init__.py")
    ast.parse(code)
    assert 'SERVICE_RESET_EMERGENCY_STATUS = "reset_emergency_status"' in code
    assert '"betrouwbare actuele status van automatische "' in code
    assert "await controller.async_reset_emergency_status(" in code
    # The intended controller call is only documented until verified sources exist.
    assert '# await controller.async_reset_emergency_status(' in code
