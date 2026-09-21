from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_central_observation_contract_is_exposed_on_shadow_sensor() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    for field in (
        "shadow_observation_contract_status",
        "shadow_observation_expected_source_count",
        "shadow_observation_configured_source_count",
        "shadow_observation_valid_source_count",
        "shadow_observation_missing_sources",
        "shadow_observation_unavailable_sources",
        "shadow_observation_invalid_sources",
        "shadow_observation_device_status",
        "shadow_observation_charge_power",
        "shadow_observation_discharge_power",
        "shadow_observation_operating_mode",
        "shadow_observation_action_direction",
        "shadow_observation_power_setpoint",
        "shadow_control_path_pre_mode_ready",
        "shadow_control_path_post_mode_required",
        "shadow_control_path_post_mode_ready",
    ):
        assert f'"{field}"' in runtime


def test_observation_contract_tracks_six_named_sources() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    for name in (
        '"device_status"',
        '"charge_power"',
        '"discharge_power"',
        '"operating_mode"',
        '"action_direction"',
        '"power_setpoint"',
    ):
        assert name in runtime
    assert '"observation_expected_source_count": len(sources)' in runtime
    assert '"observation_configured_source_count": len(configured)' in runtime
    assert '"observation_valid_source_count": len(valid)' in runtime


def test_observation_contract_is_fail_closed_and_does_not_guess() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert '"status": "not_configured"' in runtime
    assert '"status": "entity_missing"' in runtime
    assert '"status": "unavailable"' in runtime
    assert '"status": "invalid_value"' in runtime
    assert 'status = "ready"' in runtime
    assert 'status = "not_configured"' in runtime
    assert 'status = "partial"' in runtime


def test_two_stage_control_path_readiness_matches_alpha76_semantics() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert 'pre_mode_ready = bool(mode["valid"])' in runtime
    assert 'post_mode_required = mode.get("value") == "third_party_control"' in runtime
    assert 'post_mode_ready = bool(direction["valid"] and setpoint["valid"])' in runtime
    assert 'control_path_configured = bool(' in runtime


def test_observation_contract_remains_read_only() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in runtime
    assert '"automatic_execution_armed": False' in runtime
    assert '"mode_switch_service_calls_available": False' in runtime
    assert '"service_calls_performed": False' in runtime
    assert '"physical_execution_authority": False' in runtime
