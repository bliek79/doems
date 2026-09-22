from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _read(name: str) -> str:
    return (INTEGRATION / name).read_text(encoding="utf-8")


def test_step11_source_copy_files_exist_and_are_independent() -> None:
    prestart = _read("ems_prestart_validator.py")
    safety = _read("ems_safety_guard.py")

    assert "class DOEMSPreStartValidator" in prestart
    assert "class DOEMSSafetyGuard" in safety
    assert "anker_ems" not in prestart
    assert "anker_ems" not in safety
    assert ".services.async_call(" not in prestart
    assert ".services.async_call(" not in safety


def test_step11_prestart_preserves_working_source_blockers() -> None:
    prestart = _read("ems_prestart_validator.py")
    for token in (
        "planner_invalid",
        "forecast_not_ready",
        "execution_buffer_unsafe",
        "invalid_bridge_candidates",
        "bridge_invalid",
        "planner_identity_missing",
        "invalid_action",
        "invalid_power",
        "invalid_soc",
        "invalid_target_soc",
        "charge_target_already_reached",
        "discharge_target_already_reached",
        "execution_reserve_reached",
        "planner_revision_changed_after_due",
        "decision_window_min = max(15.0, start_delay)",
        '"early"',
        '"near_start"',
        '"due"',
    ):
        assert token in prestart


def test_step11_safety_handoff_preserves_working_source_blockers() -> None:
    safety = _read("ems_safety_guard.py")
    for token in (
        "prestart_not_required_for_selected_plan",
        "prestart_not_safe",
        "planner_identity_mismatch",
        "bridge_invalid",
        "forecast_not_ready",
        "execution_buffer_unsafe",
        "control_path_not_configured",
        "physical_test_active",
        "execution_already_active",
        "invalid_action",
        "invalid_power",
        "invalid_soc",
        "invalid_target_soc",
        "charge_target_already_reached",
        "discharge_target_already_reached",
        "conflicting_battery_power",
        "planner_revision_changed",
        '"auto_safety_handoff_execution_permitted": False',
        '"auto_safety_handoff_physical_control": False',
    ):
        assert token in safety


def test_step11_runtime_order_and_step12_boundary() -> None:
    runtime = _read("ems_runtime.py")
    start = runtime.index("async def _async_run_bridge_planstore_scheduler")
    end = runtime.index("    def snapshot", start)
    chain = runtime[start:end]

    positions = [
        chain.index("self.scheduler_result = self.scheduler.evaluate("),
        chain.index("refreshed_bridge = build_planner_action_bridge("),
        chain.index("self.prestart_result = self.prestart_validator.evaluate(step11_data)"),
        chain.index("self.safety_result = self.safety_guard.evaluate_automatic_handoff(step11_data)"),
    ]
    assert positions == sorted(positions)

    assert '"control_path_configured": bool(control_path.get("configured"))' in chain
    assert '"control_path_ready": control_path.get("ready")' in chain
    assert '"physical_test_active": False' in chain
    assert '"execution_active": False' in chain
    assert ".services.async_call(" not in runtime
    assert "DOEMSActionController" in runtime
    assert "ExecutionController" not in runtime
    assert '"physical_execution_authority": False' in runtime


def test_step11_runtime_exposes_diagnostics_without_execution_rights() -> None:
    runtime = _read("ems_runtime.py")
    for token in (
        '"prestart_validator_invoked": bool(prestart)',
        '"prestart_status": prestart.get("auto_prestart_status")',
        '"prestart_diagnostic_phase": prestart.get(',
        '"safety_guard_invoked": bool(safety)',
        '"safety_handoff_status": safety.get("auto_safety_handoff_status")',
        '"safety_handoff_execution_permitted": safety.get(',
        '"action_controller_invoked": bool(action_controller)',
        '"execution_controller_invoked": False',
        '"automatic_execution_armed": False',
        '"service_calls_performed": False',
        '"physical_execution_authority": False',
    ):
        assert token in runtime
