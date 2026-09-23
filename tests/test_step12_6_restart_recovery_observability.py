from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load_module():
    path = INTEGRATION / "ems_execution_shadow.py"
    spec = importlib.util.spec_from_file_location("ems_execution_shadow_step126", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _new_shadow():
    return _load_module().DOEMSExecutionControllerShadow()


def _data(
    *,
    identity: str = "laden|veiligheidsladen|2026-09-25T17:00:00+00:00|2026-09-25T18:00:00+00:00",
    armed: bool = True,
    permitted: bool = True,
    soc: float = 90,
) -> dict:
    detail = {
        "origin": "automatic_72h_planner",
        "planner_identity": identity,
        "planner_signature": identity + "|100|0.235",
        "action": "laden",
        "purpose": "veiligheidsladen",
        "power_w": 250,
        "target_soc": 100,
        "max_runtime_h": 1,
        "start_time": "2026-09-25T17:00:00+00:00",
        "planned_end_time": "2026-09-25T18:00:00+00:00",
        "planned_energy_kwh": 0.235,
    }
    return {
        "auto_execution_gate_status": "armed_ready" if armed and permitted else "ready_disarmed",
        "auto_execution_gate_execution_permitted": permitted,
        "auto_execution_gate_armed": armed,
        "auto_execution_gate_selected_slot": 1,
        "auto_execution_gate_planner_identity": identity if permitted else None,
        "auto_mode_switch_preview_switch_required": False,
        "auto_mode_switch_preview_already_external": True,
        "scheduler_slots": {1: detail},
        "soc": soc,
        "operating_mode": "third_party_control",
        "action_direction": "charge",
        "power_setpoint_w": 250,
        "charge_power_w": 250,
        "discharge_power_w": 0,
    }


def test_step12_6_completed_history_roundtrips_without_rearming() -> None:
    shadow = _new_shadow()
    start = datetime(2026, 9, 25, 17, 0, tzinfo=timezone.utc)
    shadow.evaluate(_data(), now=start)
    completed = shadow.evaluate(
        _data(armed=False, permitted=False),
        now=start + timedelta(seconds=5),
    )
    assert completed["execution_shadow_status"] == "completed_shadow"
    payload = shadow.export_persistence()

    restored = _new_shadow()
    assert restored.restore_persistence(payload) == "loaded"
    result = restored.evaluate(
        _data(armed=False, permitted=False),
        now=start + timedelta(minutes=1),
    )
    assert result["execution_shadow_active"] is False
    assert result["automatic_run_count"] == 1
    assert result["automatic_success_count"] == 1
    assert len(result["execution_shadow_run_history"]) == 1
    assert result["execution_shadow_recovery_status"] == "not_required"
    assert result["service_calls_performed"] is False
    assert result["physical_execution_authority"] is False


def test_step12_6_active_run_becomes_restart_recovery_and_never_resumes() -> None:
    shadow = _new_shadow()
    start = datetime(2026, 9, 25, 17, 0, tzinfo=timezone.utc)
    running = shadow.evaluate(_data(), now=start)
    assert running["execution_shadow_active"] is True
    payload = shadow.export_persistence()
    assert payload["active"] is True

    restored = _new_shadow()
    assert restored.restore_persistence(payload) == "loaded"
    result = restored.evaluate(
        _data(armed=False, permitted=False),
        now=start + timedelta(minutes=2),
    )
    assert result["execution_shadow_status"] == "recovered_interrupted_shadow"
    assert result["execution_shadow_active"] is False
    assert result["execution_shadow_recovery_status"] == "recovered_interrupted"
    assert result["execution_shadow_recovery_reason"] == "restart_recovery"
    assert result["execution_shadow_recovery_interrupted_run"] is True
    assert result["automatic_failure_count"] == 1
    assert result["automatic_last_run"]["reason"] == "restart_recovery"
    assert result["safe_return_required"] is True
    assert [item["operation"] for item in result["safe_return_steps"]] == [
        "set_power_zero",
        "wait",
        "switch_self_consumption",
    ]
    assert result["safe_return_performed"] is False
    assert result["service_calls_performed"] is False
    assert result["physical_execution_authority"] is False


def test_step12_6_recovered_identity_cannot_restart_same_run() -> None:
    shadow = _new_shadow()
    start = datetime(2026, 9, 25, 17, 0, tzinfo=timezone.utc)
    shadow.evaluate(_data(), now=start)
    payload = shadow.export_persistence()

    restored = _new_shadow()
    restored.restore_persistence(payload)
    restored.evaluate(
        _data(armed=False, permitted=False),
        now=start + timedelta(minutes=2),
    )
    again = restored.evaluate(
        _data(),
        now=start + timedelta(minutes=3),
    )
    assert again["execution_shadow_status"] == "recovered_interrupted_shadow"
    assert again["execution_shadow_active"] is False
    assert again["automatic_run_count"] == 1


def test_step12_6_corrupt_store_is_fail_safe() -> None:
    shadow = _new_shadow()
    assert shadow.restore_persistence("not-a-dict") == "invalid_payload"
    assert shadow.active is False

    shadow = _new_shadow()
    assert shadow.restore_persistence({"schema_version": 999, "active": True}) == "invalid_schema"
    assert shadow.active is False

    shadow = _new_shadow()
    malformed = {
        "schema_version": 1,
        "active": False,
        "run_count": "not-an-int",
        "success_count": {},
        "failure_count": [],
        "last_summary": [],
        "safe_return": "invalid",
        "frozen": "invalid",
    }
    assert shadow.restore_persistence(malformed) == "loaded"
    result = shadow.evaluate(
        _data(armed=False, permitted=False),
        now=datetime(2026, 9, 25, 17, 0, tzinfo=timezone.utc),
    )
    assert result["execution_shadow_active"] is False
    assert result["automatic_run_count"] == 0


def test_step12_6_runtime_store_and_arm_contract_is_non_actuating() -> None:
    runtime_text = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    shadow_text = (INTEGRATION / "ems_execution_shadow.py").read_text(encoding="utf-8")
    switch_text = (INTEGRATION / "switch.py").read_text(encoding="utf-8")

    assert "Store[dict[str, Any]]" in runtime_text
    assert '.execution_shadow"' in runtime_text
    assert "restore_persistence(" in runtime_text
    assert "export_persistence(" in runtime_text
    assert '"fail_safe_off_no_resume"' in runtime_text
    assert "self._automatic_execution_armed = False" in runtime_text
    assert "RestoreEntity" not in switch_text
    assert ".services.async_call(" not in shadow_text
    assert "select.select_option" not in shadow_text
    assert "number.set_value" not in shadow_text
    assert '"safe_return_performed": False' in shadow_text
    assert '"service_calls_performed": False' in shadow_text
    assert '"physical_execution_authority": False' in shadow_text
