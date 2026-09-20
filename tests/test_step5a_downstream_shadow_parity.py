from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"
ALPHA = INTEGRATION / "ems_alpha76"


def test_frozen_downstream_modules_are_present() -> None:
    for name in (
        "prestart_validator.py",
        "safety_guard.py",
        "action_controller.py",
        "execution_shadow.py",
    ):
        assert (ALPHA / name).is_file()


def test_prestart_keeps_identity_buffer_soc_and_reserve_gates() -> None:
    prestart=(ALPHA/"prestart_validator.py").read_text(encoding="utf-8")
    for token in (
        "planner_identity_match",
        "planner_signature_match",
        "execution_buffer_safe",
        "target_direction_valid",
        "execution_reserve_available",
        "bridge_candidates_valid",
        "bridge_valid",
        "forecast_ready",
    ):
        assert token in prestart
    assert "decision_window_min = max(15.0, start_delay)" in prestart
    assert '"auto_prestart_execution_enabled": False' in prestart
    assert '"auto_prestart_physical_control": False' in prestart
    assert ".services.async_call(" not in prestart


def test_automatic_safety_handoff_remains_non_actuating() -> None:
    safety=(ALPHA/"safety_guard.py").read_text(encoding="utf-8")
    assert "def evaluate_automatic_handoff" in safety
    for token in (
        "prestart_not_safe",
        "planner_identity_mismatch",
        "bridge_invalid",
        "forecast_not_ready",
        "execution_buffer_unsafe",
        "control_path_not_configured",
        "physical_test_active",
        "execution_already_active",
        "conflicting_battery_power",
    ):
        assert token in safety
    assert '"auto_safety_handoff_execution_permitted": False' in safety
    assert '"auto_safety_handoff_physical_control": False' in safety
    assert ".services.async_call(" not in safety


def test_execution_shadow_contains_only_non_actuating_evaluators() -> None:
    execution=(ALPHA/"execution_shadow.py").read_text(encoding="utf-8")
    for method in (
        "def evaluate_automatic_handoff",
        "def evaluate_final_revalidation",
        "def evaluate_mode_switch_transaction",
    ):
        assert method in execution
    assert "async def async_run_" not in execution
    assert ".services.async_call(" not in execution
    assert '"auto_execution_handoff_execution_permitted": False' in execution
    assert '"auto_final_revalidation_execution_permitted": False' in execution
    assert '"auto_mode_switch_preview_execution_permitted": False' in execution
    assert '"auto_mode_switch_preview_physical_control": False' in execution


def test_legacy_action_controller_is_preview_only() -> None:
    controller=(ALPHA/"action_controller.py").read_text(encoding="utf-8")
    assert "controller_desired_mode" in controller
    assert "controller_desired_direction" in controller
    assert "controller_desired_power_w" in controller
    assert '"controller_physical_control": False' in controller
    assert ".services.async_call(" not in controller


def test_runtime_orders_downstream_gates_like_alpha76() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    order=[
        "work.update(self.prestart.evaluate(work))",
        "work.update(self.safety_guard.evaluate_automatic_handoff(work))",
        "work.update(self.execution_gates.evaluate_automatic_handoff(work))",
        "work.update(self.execution_gates.evaluate_final_revalidation(work))",
        "work.update(self.execution_gates.evaluate_mode_switch_transaction(work))",
        "work.update(self.safety_guard.evaluate(work))",
        "work.update(self.action_controller.evaluate(work))",
    ]
    positions=[runtime.index(item) for item in order]
    assert positions == sorted(positions)


def test_runtime_hard_closes_physical_execution_boundary() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert '"physical_test_active": False' in runtime
    assert '"execution_active": False' in runtime
    assert '"simulation_mode": True' in runtime
    assert '"automatic_execution_armed": False' in runtime
    assert '"mode_switch_service_calls_available": False' in runtime
    assert '"service_calls_performed": False' in runtime
    assert '"physical_execution_authority": False' in runtime
    assert ".services.async_call(" not in runtime


def test_optional_read_only_observation_contract_is_configurable() -> None:
    const=(INTEGRATION/"const.py").read_text(encoding="utf-8")
    flow=(INTEGRATION/"config_flow.py").read_text(encoding="utf-8")
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    fields=(
        "CONF_DEVICE_STATUS_ENTITY",
        "CONF_CHARGE_POWER_ENTITY",
        "CONF_DISCHARGE_POWER_ENTITY",
        "CONF_OPERATING_MODE_ENTITY",
        "CONF_ACTION_DIRECTION_ENTITY",
        "CONF_POWER_SETPOINT_ENTITY",
    )
    for field in fields:
        assert field in const
        assert field in flow
        assert field in runtime
    assert "ems_observation_state_change" in runtime
    assert "control_path_configured" in runtime
