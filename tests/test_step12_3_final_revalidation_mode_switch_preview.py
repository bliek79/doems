from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _read(name: str) -> str:
    return (INTEGRATION / name).read_text(encoding="utf-8")


def test_step12_3_contract_is_present_and_non_actuating() -> None:
    final = _read("ems_final_revalidation.py")
    preview = _read("ems_mode_switch_preview.py")
    runtime = _read("ems_runtime.py")
    assert "class DOEMSFinalRevalidation" in final
    assert "class DOEMSModeSwitchPreview" in preview
    assert "auto_final_revalidation_safe" in runtime
    assert "auto_mode_switch_preview_status" in runtime
    for content in (final, preview):
        assert ".services.async_call(" not in content
        assert "select.select_option" not in content
        assert "number.set_value" not in content
        assert '"physical_execution_authority": False' in content
        assert '"service_calls_performed": False' in content


def test_step12_3_preview_keeps_execution_fenced() -> None:
    preview = _read("ems_mode_switch_preview.py")
    for token in (
        '"auto_mode_switch_preview_preview_only": True',
        '"auto_mode_switch_preview_transaction_started": False',
        '"auto_mode_switch_preview_mode_switch_performed": False',
        '"auto_mode_switch_preview_direction_written": False',
        '"auto_mode_switch_preview_power_setpoint_written": False',
        '"auto_mode_switch_preview_execution_controller_released": False',
        '"automatic_execution_armed": False',
        '"auto_mode_switch_preview_execution_permitted": False',
        '"auto_mode_switch_preview_physical_control": False',
    ):
        assert token in preview


def test_step12_3_source_parity_safety_stages_are_previewed() -> None:
    preview = _read("ems_mode_switch_preview.py")
    for token in (
        "set_zero_power_guard",
        "third_party_control",
        "wait_stable",
        "post_mode_revalidation",
        "safe_return_self_consumption",
    ):
        assert token in preview


def test_step12_3_runtime_does_not_open_step12_4() -> None:
    runtime = _read("ems_runtime.py")
    assert '"execution_controller_invoked": False' in runtime
    assert '"automatic_execution_armed": False' in runtime
    assert '"service_calls_performed": False' in runtime
    assert '"physical_execution_authority": False' in runtime
