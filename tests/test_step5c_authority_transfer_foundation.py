from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load_step5c():
    spec = importlib.util.spec_from_file_location("ems_step5c_test", INTEGRATION / "ems_step5c.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_step5c_disarmed_foundation_keeps_doems_non_actuating() -> None:
    m = _load_step5c()
    result = m.build_step5c_disarmed_foundation(
        {
            "charge_power_w": 0,
            "discharge_power_w": 0,
            "power_setpoint_w": None,
            "operating_mode": "self_consumption",
        },
        legacy_automatic_state="on",
        legacy_authority_state="open",
        legacy_authority_attributes={
            "write_fence": "open",
            "authority_generation": 4,
            "inflight_calls": 0,
            "write_count": 12,
        },
    )
    assert result["step5c_phase"] == "ACTIVE_LEGACY"
    assert result["authority_owner"] == "anker_ems"
    assert result["authority_generation"] == 4
    assert result["doems_write_fence"] == "closed"
    assert result["step5c_live_transfer_enabled"] is False
    assert result["step5c_arm_available"] is False
    assert result["step5c_service_calls_performed"] is False
    assert result["automatic_execution_armed"] is False
    assert result["physical_execution_authority"] is False
    assert "legacy_automatic_execution_on" in result["cutover_blockers"]
    assert "legacy_write_fence_open" in result["cutover_blockers"]


def test_automatic_execution_off_is_not_authority_release() -> None:
    m = _load_step5c()
    result = m.build_step5c_disarmed_foundation(
        {
            "charge_power_w": 0,
            "discharge_power_w": 0,
            "power_setpoint_w": 0,
            "operating_mode": "self_consumption",
        },
        legacy_automatic_state="off",
        legacy_authority_state="open",
        legacy_authority_attributes={"write_fence": "open", "inflight_calls": 0},
    )
    assert result["legacy_manual_mode"] is True
    assert result["legacy_quiesced"] is False
    assert result["authority_owner"] == "anker_ems"
    assert "legacy_write_fence_open" in result["cutover_blockers"]


def test_closed_legacy_fence_can_be_observed_without_claiming_doems() -> None:
    m = _load_step5c()
    result = m.build_step5c_disarmed_foundation(
        {
            "charge_power_w": 0,
            "discharge_power_w": 0,
            "power_setpoint_w": 0,
            "operating_mode": "self_consumption",
        },
        legacy_automatic_state="off",
        legacy_authority_state="closed",
        legacy_authority_attributes={
            "write_fence": "closed",
            "inflight_calls": 0,
            "authority_generation": 7,
        },
    )
    assert result["legacy_quiesced"] is True
    assert result["zero_power_observed"] is True
    assert result["safe_return_observed"] is True
    assert result["zero_power_verified"] is False
    assert result["safe_return_verified"] is False
    assert result["authority_owner"] == "anker_ems"
    assert result["physical_execution_authority"] is False
    assert result["cutover_blockers"] == ["step5c_live_transfer_disabled"]


def test_step5c_runtime_contract_has_no_physical_service_path() -> None:
    step5c = (INTEGRATION / "ems_step5c.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "ems_shadow_runtime.py").read_text(encoding="utf-8")
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in step5c
    assert ".services.async_call(" not in runtime
    assert 'CONF_LEGACY_AUTOMATIC_EXECUTION_ENTITY = "legacy_automatic_execution_entity"' in const
    assert 'CONF_LEGACY_AUTHORITY_ENTITY = "legacy_authority_entity"' in const
    assert "build_step5c_disarmed_foundation(" in runtime
    assert '"step5c_live_transfer_enabled"' in runtime
    assert '"physical_execution_authority": False' in runtime
