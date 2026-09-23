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


def _load_module(name: str):
    import importlib.util
    path = INTEGRATION / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ready_data() -> dict:
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    detail = {
        "origin": "automatic_72h_planner",
        "lifecycle_status": "pending",
        "planner_identity": "stable-id",
        "planner_signature": "rev-1",
        "action": "laden",
        "purpose": "veiligheidsladen",
        "power_w": 1800,
        "target_soc": 60,
        "max_runtime_h": 2,
        "start_time": (now - timedelta(minutes=1)).isoformat(),
        "max_start_delay_min": 10,
    }
    return {
        "scheduler_slots": {1: detail},
        "scheduler_selected_slot": 1,
        "scheduler_ready": True,
        "auto_execution_handoff_selected_slot": 1,
        "auto_execution_handoff_required": True,
        "auto_execution_handoff_ready": True,
        "auto_execution_handoff_planner_identity": "stable-id",
        "auto_prestart_required": True,
        "auto_prestart_safe": True,
        "auto_prestart_current_identity_match": True,
        "auto_prestart_current_signature_match": True,
        "auto_prestart_execution_reserve_soc": 30,
        "auto_safety_handoff_safe": True,
        "auto_plan_72h_valid": True,
        "auto_plan_72h_execution_buffer_safe": False,
        "forecast_ready": True,
        "soc": 40,
        "technical_min_soc_percent": 5,
        "max_soc_percent": 100,
        "max_charge_power_w": 3200,
        "max_discharge_power_w": 3200,
        "charge_power_w": 0,
        "discharge_power_w": 0,
        "control_path_configured": True,
        "control_path_pre_mode_ready": True,
        "control_path_post_mode_ready": False,
        "control_path_required_stable_seconds": 60,
        "control_path_pre_mode_stable_seconds": 120,
        "control_path_post_mode_stable_seconds": 0,
        "control_path_operating_mode_available": True,
        "control_path_entities": {
            "operating_mode": {"entity_id": "select.mode", "available": True},
            "action_direction": {"entity_id": "select.direction", "available": False},
            "power_setpoint": {"entity_id": "number.power", "available": False},
        },
        "operating_mode": "self_consumption",
        "physical_test_active": False,
        "execution_active": False,
    }


def test_step12_3_ready_charge_previews_switch_without_authority() -> None:
    final_mod = _load_module("ems_final_revalidation.py")
    preview_mod = _load_module("ems_mode_switch_preview.py")
    data = _ready_data()
    final = final_mod.DOEMSFinalRevalidation().evaluate(data)
    assert final["auto_final_revalidation_safe"] is True
    assert final["auto_final_revalidation_status"] == "ready"
    assert "external_mode_switch_required" in final["auto_final_revalidation_warnings"]
    preview = preview_mod.DOEMSModeSwitchPreview().evaluate({**data, **final})
    assert preview["auto_mode_switch_preview_ready"] is True
    assert preview["auto_mode_switch_preview_status"] == "switch_required"
    assert preview["auto_mode_switch_preview_direction"] == "charge"
    assert preview["auto_mode_switch_preview_transaction_started"] is False
    assert preview["physical_execution_authority"] is False


def test_step12_3_signature_change_is_warning_but_identity_mismatch_blocks() -> None:
    final_mod = _load_module("ems_final_revalidation.py")
    data = _ready_data()
    data["auto_prestart_current_signature_match"] = False
    final = final_mod.DOEMSFinalRevalidation().evaluate(data)
    assert final["auto_final_revalidation_safe"] is True
    assert "planner_revision_changed" in final["auto_final_revalidation_warnings"]
    data["auto_prestart_current_identity_match"] = False
    blocked = final_mod.DOEMSFinalRevalidation().evaluate(data)
    assert blocked["auto_final_revalidation_safe"] is False
    assert "planner_identity_mismatch" in blocked["auto_final_revalidation_reasons"]


def test_step12_3_target_reached_blocks_and_external_requires_post_mode() -> None:
    final_mod = _load_module("ems_final_revalidation.py")
    preview_mod = _load_module("ems_mode_switch_preview.py")
    data = _ready_data()
    data["soc"] = 60
    blocked = final_mod.DOEMSFinalRevalidation().evaluate(data)
    assert blocked["auto_final_revalidation_safe"] is False
    assert "target_already_reached" in blocked["auto_final_revalidation_reasons"]

    data = _ready_data()
    data["operating_mode"] = "third_party_control"
    data["control_path_entities"]["action_direction"]["available"] = True
    data["control_path_entities"]["power_setpoint"]["available"] = True
    final = final_mod.DOEMSFinalRevalidation().evaluate(data)
    assert final["auto_final_revalidation_safe"] is True
    preview = preview_mod.DOEMSModeSwitchPreview().evaluate({**data, **final})
    assert preview["auto_mode_switch_preview_status"] == "blocked"
    assert "post_mode_not_ready" in preview["auto_mode_switch_preview_blockers"]
    data["control_path_post_mode_ready"] = True
    data["control_path_post_mode_stable_seconds"] = 120
    final = final_mod.DOEMSFinalRevalidation().evaluate(data)
    preview = preview_mod.DOEMSModeSwitchPreview().evaluate({**data, **final})
    assert preview["auto_mode_switch_preview_status"] == "already_external"
