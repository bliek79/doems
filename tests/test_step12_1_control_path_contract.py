from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _read(name: str) -> str:
    return (INTEGRATION / name).read_text(encoding="utf-8")


def test_step12_1_control_path_observer_is_read_only_and_source_parity() -> None:
    module = _read("ems_control_path.py")
    for token in (
        "class DOEMSControlPathObserver",
        'CONTROL_PATH_STABLE_SECONDS',
        '"third_party_control"',
        '"operating_mode_unavailable"',
        '"operating_mode_not_stable"',
        '"awaiting_third_party_control"',
        'f"{key}_unavailable"',
        'f"{key}_not_stable"',
        '"control_path_ready"',
        '"read_only": True',
        '"service_calls_performed": False',
        '"physical_execution_authority": False',
    ):
        assert token in module

    assert ".services.async_call(" not in module
    assert "async_call(" not in module
    assert "select_option" not in module
    assert "set_value" not in module


def test_step12_1_runtime_consumes_real_control_path_without_execution() -> None:
    runtime = _read("ems_runtime.py")
    for token in (
        "DOEMSControlPathObserver",
        "self.control_path = DOEMSControlPathObserver(hass, entry)",
        'self.control_path_result = self.control_path.evaluate()',
        '"control_path_configured": bool(control_path.get("configured"))',
        '"control_path_ready": control_path.get("ready")',
        '"operating_mode": control_entities.get("operating_mode", {}).get("state")',
        '"action_direction": control_entities.get("action_direction", {}).get("state")',
        '"power_setpoint_w": control_entities.get("power_setpoint", {}).get("state")',
        '"automatic_execution_armed": False',
        '"service_calls_performed": False',
        '"physical_execution_authority": False',
    ):
        assert token in runtime

    assert ".services.async_call(" not in runtime
    assert "ExecutionController" not in runtime


def test_step12_1_configuration_contract_is_optional_but_complete_when_used() -> None:
    const = _read("const.py")
    flow = _read("config_flow.py")
    for token in (
        'CONF_OPERATING_MODE_ENTITY = "operating_mode_entity"',
        'CONF_ACTION_DIRECTION_ENTITY = "action_direction_entity"',
        'CONF_POWER_SETPOINT_ENTITY = "power_setpoint_entity"',
        "CONTROL_PATH_STABLE_SECONDS = 60",
    ):
        assert token in const

    for token in (
        "CONF_OPERATING_MODE_ENTITY",
        "CONF_ACTION_DIRECTION_ENTITY",
        "CONF_POWER_SETPOINT_ENTITY",
        '"control_path_incomplete"',
        '_entity_selector("select")',
        '_entity_selector("number")',
    ):
        assert token in flow


def test_step12_1_step11_boundary_evolves_without_physical_authority() -> None:
    runtime = _read("ems_runtime.py")
    assert '"control_path_configured": False' not in runtime
    assert '"physical_test_active": False' in runtime
    assert '"execution_active": False' in runtime
    assert '"action_controller_invoked": False' in runtime
    assert '"execution_controller_invoked": False' in runtime
    assert '"automatic_execution_armed": False' in runtime
    assert '"service_calls_performed": False' in runtime
    assert '"physical_execution_authority": False' in runtime
