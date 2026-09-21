from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load_step5b():
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    return importlib.import_module("custom_components.doems.ems_step5b")


def _ready_data() -> dict:
    return {
        "scheduler_selected_slot": 1,
        "scheduler_ready": True,
        "scheduler_slots": {
            1: {
                "origin": "automatic_72h_planner",
                "lifecycle_status": "pending",
                "action": "laden",
                "purpose": "veiligheidsladen",
                "planner_identity": "identity-1",
                "planner_signature": "signature-1",
                "start_time": "2026-09-21T12:45:00+00:00",
                "planned_end_time": "2026-09-21T13:45:00+00:00",
                "power_w": 480,
                "target_soc": 87.9,
                "max_runtime_h": 1.0,
                "planned_energy_kwh": 0.462,
                "price_sources": [],
                "all_prices_known": False,
            }
        },
        "auto_shadow_status": "ready_disarmed",
        "auto_shadow_technical_ready": True,
        "auto_shadow_armed": False,
        "auto_shadow_execution_permitted": False,
        "auto_shadow_manual_override_active": False,
        "auto_shadow_control_path_ready": True,
        "auto_prestart_safe": True,
        "auto_safety_handoff_safe": True,
        "auto_execution_handoff_ready": True,
        "auto_final_revalidation_safe": True,
        "auto_mode_switch_preview_ready": True,
        "control_path_configured": True,
        "control_path_post_mode_ready": False,
        "physical_test_active": False,
        "execution_active": False,
        "forecast_ready": True,
        "max_charge_power_w": 3200,
        "max_discharge_power_w": 3200,
        "soc": 82.0,
        "operating_mode": "self_consumption",
        "action_direction": None,
        "power_setpoint_w": None,
    }


def test_ready_disarmed_builds_immutable_prepared_envelope() -> None:
    m = _load_step5b()
    data = _ready_data()
    envelope, blockers, warnings = m.build_execution_envelope(data)
    assert blockers == []
    assert warnings == ["forecast_price_used_for_non_trade_planning"]
    assert envelope is not None
    first = envelope.fingerprint
    second = envelope.fingerprint
    assert first == second
    assert len(first) == 64

    result = m.build_step5b_rehearsal(data, previous_envelope=envelope)
    assert result["step5b_status"] == "prepared_disarmed"
    assert result["step5b_transaction_phase"] == "COMPLETE_DISARMED"
    assert result["step5b_transaction_ready"] is True
    assert result["step5b_authority_fence"] is False
    assert result["step5b_service_calls_performed"] is False
    assert result["automatic_execution_armed"] is False
    assert result["physical_execution_authority"] is False


def test_signature_change_after_capture_aborts_fail_closed() -> None:
    m = _load_step5b()
    data = _ready_data()
    envelope, blockers, _warnings = m.build_execution_envelope(data)
    assert envelope is not None and blockers == []

    changed = _ready_data()
    changed["scheduler_slots"][1]["planner_signature"] = "signature-2"
    result = m.build_step5b_rehearsal(changed, previous_envelope=envelope)
    assert result["step5b_status"] == "aborted_disarmed"
    assert result["step5b_transaction_phase"] == "ABORTED_DISARMED"
    assert "planner_signature_changed_after_capture" in result["step5b_blockers"]
    assert result["step5b_transaction_ready"] is False
    assert result["step5b_authority_fence"] is False


def test_identity_slot_action_and_purpose_changes_abort() -> None:
    m = _load_step5b()
    data = _ready_data()
    envelope, blockers, _warnings = m.build_execution_envelope(data)
    assert envelope is not None and blockers == []

    mutations = (
        ("planner_identity", "identity-2", "planner_identity_changed"),
        ("action", "ontladen", "action_changed"),
        ("purpose", "handelsladen", "purpose_changed"),
    )
    for field, value, expected in mutations:
        changed = _ready_data()
        changed["scheduler_slots"][1][field] = value
        result = m.build_step5b_rehearsal(changed, previous_envelope=envelope)
        assert result["step5b_status"] == "aborted_disarmed"
        assert expected in result["step5b_blockers"]

    changed = _ready_data()
    changed["scheduler_selected_slot"] = 2
    changed["scheduler_slots"][2] = changed["scheduler_slots"].pop(1)
    result = m.build_step5b_rehearsal(changed, previous_envelope=envelope)
    assert "selected_slot_changed" in result["step5b_blockers"]


def test_self_consumption_does_not_require_post_mode_entities() -> None:
    m = _load_step5b()
    data = _ready_data()
    assert data["operating_mode"] == "self_consumption"
    assert data["action_direction"] is None
    assert data["power_setpoint_w"] is None
    envelope, blockers, _warnings = m.build_execution_envelope(data)
    assert envelope is not None and blockers == []
    result = m.build_step5b_rehearsal(data, previous_envelope=envelope)
    assert result["step5b_status"] == "prepared_disarmed"


def test_external_mode_requires_post_mode_readiness_and_no_conflict() -> None:
    m = _load_step5b()
    data = _ready_data()
    envelope, blockers, _warnings = m.build_execution_envelope(data)
    assert envelope is not None and blockers == []

    external = _ready_data()
    external["operating_mode"] = "third_party_control"
    external["control_path_post_mode_ready"] = False
    external["action_direction"] = "discharge"
    external["power_setpoint_w"] = 1900
    result = m.build_step5b_rehearsal(external, previous_envelope=envelope)
    assert result["step5b_status"] == "aborted_disarmed"
    for blocker in (
        "post_mode_not_ready",
        "external_direction_conflict",
        "external_power_setpoint_conflict",
    ):
        assert blocker in result["step5b_blockers"]


def test_target_reached_and_manual_override_abort() -> None:
    m = _load_step5b()
    data = _ready_data()
    envelope, blockers, _warnings = m.build_execution_envelope(data)
    assert envelope is not None and blockers == []

    reached = _ready_data()
    reached["soc"] = 90.0
    result = m.build_step5b_rehearsal(reached, previous_envelope=envelope)
    assert "charge_target_already_reached" in result["step5b_blockers"]

    manual = _ready_data()
    manual["auto_shadow_manual_override_active"] = True
    result = m.build_step5b_rehearsal(manual, previous_envelope=envelope)
    assert "manual_override_active" in result["step5b_blockers"]


def test_trade_without_known_prices_cannot_build_envelope() -> None:
    m = _load_step5b()
    data = _ready_data()
    data["scheduler_slots"][1]["purpose"] = "handelsladen"
    envelope, blockers, _warnings = m.build_execution_envelope(data)
    assert envelope is None
    assert "trade_requires_known_prices" in blockers


def test_rehearsal_phase_contract_is_complete_and_non_actuating() -> None:
    m = _load_step5b()
    assert m.REHEARSAL_PHASES == (
        "PRECHECK",
        "ZERO_POWER_INTENT",
        "MODE_SWITCH_INTENT",
        "WAIT_POST_MODE_INTENT",
        "POST_MODE_REVALIDATION",
        "DIRECTION_INTENT",
        "POWER_INTENT",
        "MONITOR_INTENT",
        "SAFE_RETURN_INTENT",
        "COMPLETE_DISARMED",
    )
    source = (INTEGRATION / "ems_step5b.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "async def async_run_" not in source
    assert "async def async_execute_" not in source


def test_runtime_keeps_step5b_ephemeral_and_authority_closed() -> None:
    runtime = (INTEGRATION / "ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert "self.step5b_envelope: ExecutionEnvelope | None = None" in runtime
    assert "build_step5b_rehearsal(" in runtime
    assert '"step5b_authority_fence": False' in runtime
    assert '"step5b_service_calls_performed": False' in runtime
    assert '"automatic_execution_armed": False' in runtime
    assert '"service_calls_performed": False' in runtime
    assert '"physical_execution_authority": False' in runtime
    assert "Store[" not in (INTEGRATION / "ems_step5b.py").read_text(encoding="utf-8")
