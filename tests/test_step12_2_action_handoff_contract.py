from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _read(name: str) -> str:
    return (INTEGRATION / name).read_text(encoding="utf-8")


def test_step12_2_action_controller_is_source_parity_and_non_actuating() -> None:
    module = _read("ems_action_controller.py")
    for token in (
        "class DOEMSActionController",
        '"controller_status": "idle"',
        '"controller_status": "geblokkeerd"',
        '"voorbereid_simulatie"',
        '"voorbereid_observe"',
        '"controller_desired_mode": "third_party_control"',
        '"controller_desired_direction": detail.get("action")',
        '"controller_desired_power_w": detail.get("power_w")',
        '"controller_physical_control": False',
    ):
        assert token in module
    assert ".services.async_call(" not in module
    assert "select_option" not in module
    assert "set_value" not in module


def test_step12_2_automatic_handoff_preserves_source_blockers_and_warnings() -> None:
    module = _read("ems_execution_handoff.py")
    for token in (
        "class DOEMSExecutionHandoff",
        "safety_handoff_not_safe",
        "prestart_not_safe",
        "planner_identity_mismatch",
        "planner_identity_missing",
        "invalid_action",
        "invalid_power",
        "invalid_target_soc",
        "invalid_runtime",
        "control_path_not_configured",
        "physical_test_active",
        "execution_already_active",
        "external_mode_switch_required",
        "planner_revision_changed",
        '"auto_execution_handoff_execution_permitted": False',
        '"auto_execution_handoff_physical_control": False',
    ):
        assert token in module
    assert "Final Revalidation" in module
    assert ".services.async_call(" not in module
    assert "select_option" not in module
    assert "set_value" not in module


def test_step12_2_runtime_keeps_manual_and_automatic_paths_separate() -> None:
    runtime = _read("ems_runtime.py")
    start = runtime.index("async def _async_run_bridge_planstore_scheduler")
    end = runtime.index("    def snapshot", start)
    chain = runtime[start:end]

    assert "self.legacy_safety_result = self.safety_guard.evaluate(step12_data)" in chain
    assert "self.action_controller_result = self.action_controller.evaluate(action_data)" in chain
    assert "self.execution_handoff_result = self.execution_handoff.evaluate(execution_data)" in chain

    action_pos = chain.index("self.action_controller_result = self.action_controller.evaluate(action_data)")
    handoff_pos = chain.index("self.execution_handoff_result = self.execution_handoff.evaluate(execution_data)")
    assert action_pos < handoff_pos

    # The automatic execution-handoff consumes Safety/Prestart data directly.
    # It must not depend on Action Controller outputs.
    handoff_block = chain[handoff_pos - 400:handoff_pos + 300]
    assert "action_controller_result" not in handoff_block

    assert ".services.async_call(" not in runtime
    assert '"execution_controller_invoked": False' in runtime
    assert '"automatic_execution_armed": False' in runtime
    assert '"service_calls_performed": False' in runtime
    assert '"physical_execution_authority": False' in runtime


def test_step12_2_runtime_exposes_shadow_diagnostics() -> None:
    runtime = _read("ems_runtime.py")
    for token in (
        '"action_controller_invoked": bool(action_controller)',
        '"controller_status": action_controller.get("controller_status")',
        '"controller_ready": action_controller.get("controller_ready")',
        '"execution_handoff_invoked": bool(execution_handoff)',
        '"execution_handoff_status": execution_handoff.get("auto_execution_handoff_status")',
        '"execution_handoff_ready": execution_handoff.get("auto_execution_handoff_ready")',
        '"execution_handoff_execution_permitted": execution_handoff.get(',
        '"execution_controller_invoked": False',
        '"automatic_execution_armed": False',
        '"service_calls_performed": False',
        '"physical_execution_authority": False',
    ):
        assert token in runtime


def test_step12_2_does_not_implement_step12_3() -> None:
    integration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in INTEGRATION.glob("ems_*.py")
    )
    assert "class DOEMSFinalRevalidation" not in integration_text
    assert "class DOEMSModeSwitch" not in integration_text
    assert "automatic_execution_armed = True" not in integration_text
