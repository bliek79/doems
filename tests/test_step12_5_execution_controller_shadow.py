from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load_shadow():
    path = INTEGRATION / "ems_execution_shadow.py"
    spec = importlib.util.spec_from_file_location("ems_execution_shadow", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DOEMSExecutionControllerShadow()


def _data(
    *,
    identity: str = "laden|veiligheidsladen|2026-09-23T14:45:00+00:00|2026-09-23T15:45:00+00:00",
    requested_power: float = 250,
    setpoint: float = 250,
    mode: str = "third_party_control",
    direction: str = "charge",
    soc: float = 97,
    planned_energy: float = 0.235,
    armed: bool = True,
    permitted: bool = True,
    already_external: bool = True,
) -> dict:
    detail = {
        "origin": "automatic_72h_planner",
        "planner_identity": identity,
        "planner_signature": identity + "|100|0.235",
        "action": "laden",
        "purpose": "veiligheidsladen",
        "power_w": requested_power,
        "target_soc": 100,
        "max_runtime_h": 1,
        "start_time": "2026-09-23T14:45:00+00:00",
        "planned_end_time": "2026-09-23T15:45:00+00:00",
        "planned_energy_kwh": planned_energy,
    }
    return {
        "auto_execution_gate_status": "armed_ready" if armed and permitted else "ready_disarmed",
        "auto_execution_gate_execution_permitted": permitted,
        "auto_execution_gate_armed": armed,
        "auto_execution_gate_selected_slot": 1,
        "auto_execution_gate_planner_identity": identity if permitted else None,
        "auto_mode_switch_preview_switch_required": not already_external,
        "auto_mode_switch_preview_already_external": already_external,
        "scheduler_slots": {1: detail},
        "soc": soc,
        "operating_mode": mode,
        "action_direction": direction,
        "power_setpoint_w": setpoint,
        "charge_power_w": max(0.0, setpoint) if direction == "charge" else 0.0,
        "discharge_power_w": max(0.0, setpoint) if direction == "discharge" else 0.0,
    }


def test_step12_5_armed_ready_starts_non_actuating_shadow() -> None:
    shadow = _load_shadow()
    now = datetime(2026, 9, 23, 14, 49, tzinfo=timezone.utc)
    result = shadow.evaluate(_data(), now=now)
    assert result["execution_shadow_status"] == "running_shadow"
    assert result["execution_shadow_active"] is True
    assert result["execution_shadow_identity"]
    assert result["runtime_safety_safe"] is True
    assert result["service_calls_performed"] is False
    assert result["physical_execution_authority"] is False
    assert result["execution_controller_invoked"] is False
    assert all(step["physical"] is False for step in result["execution_shadow_transaction"])


def test_step12_5_power_setpoint_mismatch_emergency_stops_shadow() -> None:
    shadow = _load_shadow()
    now = datetime(2026, 9, 23, 14, 49, tzinfo=timezone.utc)
    result = shadow.evaluate(_data(setpoint=370), now=now)
    assert result["execution_shadow_status"] == "emergency_stopped_shadow"
    assert result["safe_return_required"] is True
    assert result["safe_return_status"] == "preview_ready"
    assert result["safe_return_performed"] is False
    assert result["service_calls_performed"] is False
    assert result["physical_execution_authority"] is False
    assert result["automatic_failure_count"] == 1
    assert result["automatic_last_run"]["reason"] == "power_setpoint_changed"


def test_step12_5_signature_does_not_mutate_frozen_run_but_identity_conflict_stops() -> None:
    shadow = _load_shadow()
    start = datetime(2026, 9, 23, 14, 49, tzinfo=timezone.utc)
    first = shadow.evaluate(_data(), now=start)
    frozen = first["execution_shadow_identity"]

    revised = _data()
    revised["scheduler_slots"][1]["planner_signature"] = "revision-2"
    second = shadow.evaluate(revised, now=start + timedelta(seconds=5))
    assert second["execution_shadow_status"] == "running_shadow"
    assert second["execution_shadow_identity"] == frozen

    conflict = _data(identity="different-identity")
    conflict["auto_execution_gate_planner_identity"] = "different-identity"
    third = shadow.evaluate(conflict, now=start + timedelta(seconds=10))
    assert third["execution_shadow_status"] == "emergency_stopped_shadow"
    assert third["automatic_last_run"]["reason"] == "runtime_identity_changed"


def test_step12_5_disarm_is_normal_safe_return_request() -> None:
    shadow = _load_shadow()
    start = datetime(2026, 9, 23, 14, 49, tzinfo=timezone.utc)
    shadow.evaluate(_data(), now=start)
    disarmed = _data(armed=False, permitted=False)
    result = shadow.evaluate(disarmed, now=start + timedelta(seconds=5))
    assert result["execution_shadow_status"] == "completed_shadow"
    assert result["safe_return_required"] is True
    assert result["automatic_success_count"] == 1
    assert result["automatic_last_run"]["reason"] == "automatic_execution_disarmed"


def test_step12_5_target_soc_is_normal_completion() -> None:
    shadow = _load_shadow()
    start = datetime(2026, 9, 23, 14, 49, tzinfo=timezone.utc)
    shadow.evaluate(_data(), now=start)
    result = shadow.evaluate(_data(soc=100), now=start + timedelta(seconds=5))
    assert result["execution_shadow_status"] == "completed_shadow"
    assert result["automatic_last_run"]["reason"] == "target_soc_reached"


def test_step12_5_planned_energy_is_primary_completion_condition() -> None:
    shadow = _load_shadow()
    start = datetime(2026, 9, 23, 14, 49, tzinfo=timezone.utc)
    high_power = _data(requested_power=1000, setpoint=1000, planned_energy=0.01)
    high_power["charge_power_w"] = 1000
    shadow.evaluate(high_power, now=start)
    result = shadow.evaluate(high_power, now=start + timedelta(seconds=30))
    assert result["execution_shadow_status"] == "completed_shadow"
    assert result["automatic_last_run"]["reason"] == "planned_energy_reached"


def test_step12_5_preview_only_mode_switch_does_not_fail_on_untransitioned_physical_state() -> None:
    shadow = _load_shadow()
    start = datetime(2026, 9, 23, 14, 49, tzinfo=timezone.utc)
    data = _data(
        already_external=False,
        mode="self_consumption",
        direction="charge",
        setpoint=0,
    )
    data["charge_power_w"] = 0
    result = shadow.evaluate(data, now=start)
    assert result["execution_shadow_status"] == "running_shadow"
    assert result["runtime_safety_safe"] is True
    assert "physical_state_not_transitioned_shadow" in result["runtime_safety_warnings"]


def test_step12_5_safe_return_sequence_is_fixed_and_non_actuating() -> None:
    shadow = _load_shadow()
    start = datetime(2026, 9, 23, 14, 49, tzinfo=timezone.utc)
    result = shadow.evaluate(_data(setpoint=370), now=start)
    steps = result["safe_return_steps"]
    assert [step["operation"] for step in steps] == [
        "set_power_zero",
        "wait",
        "switch_self_consumption",
    ]
    assert steps[0]["requested_value"] == 0
    assert steps[1]["seconds"] == 1
    assert steps[2]["requested_value"] == "self_consumption"
    assert all(step["physical"] is False for step in steps)


def test_step12_5_source_and_runtime_have_no_physical_execution() -> None:
    shadow_text = (INTEGRATION / "ems_execution_shadow.py").read_text(encoding="utf-8")
    runtime_text = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in shadow_text
    assert "select.select_option" not in shadow_text
    assert "number.set_value" not in shadow_text
    assert '"service_calls_performed": False' in shadow_text
    assert '"physical_execution_authority": False' in shadow_text
    assert '"execution_controller_invoked": False' in shadow_text
    assert "self.execution_shadow.evaluate(" in runtime_text
    assert "self._request_refresh(\"execution_shadow_monitor\")" in runtime_text
