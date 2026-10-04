from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"

def _blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def _read(name: str) -> str:
    return (INTEGRATION / name).read_text(encoding="utf-8")

def test_alpha36_candidate_identity_keeps_alpha32_source_parity_contract() -> None:
    assert 'VERSION = "0.1.0-alpha.36"' in _read("const.py")
    assert json.loads(_read("manifest.json"))["version"] == "0.1.0-alpha.36"

def test_source_verified_alpha76_modules_are_frozen() -> None:
    expected = {
        "ems_execution.py": "82079d53144eb2cc52abd3f1e2e857f7a6fb7812",
        "ems_physical_test.py": "215fba3cda0346b147d25f69b11c7ab53583ff2b",
        "ems_scheduler.py": "2516c7c63ac524b300fdef1c00d2e75651957091",
        "ems_prestart_validator.py": "d8a958064a29f12860dd2f2e1dfbd7f87d37ae57",
        "ems_safety_guard.py": "70c678b5df59a6a29369cda4e700a3ec49637d2f",
        "ems_action_controller.py": "fa6f1818e9b29db5b57cbe12a816b946fc4f3c0e",
    }
    for name, sha in expected.items():
        assert _blob_sha(INTEGRATION / name) == sha, name

def test_exact_alpha76_planner_blobs_remain_byte_identical() -> None:
    expected = {
        "energy_need.py": "83bcdbb35d1b59247a4ee29e4600b1112eb83ebb",
        "planner_preview.py": "0ab7c59be0c414d39dda9cbcd46598af9cf7c4a3",
        "planner_72h.py": "d9cd3bb306da5f7e608d558a2b28d7366931e29b",
    }
    base = INTEGRATION / "ems_alpha76"
    for name, sha in expected.items():
        assert _blob_sha(base / name) == sha, name

def test_bridge_is_alpha76_plus_only_quarter_roll_transport_adapter() -> None:
    assert _blob_sha(INTEGRATION / "ems_planner_bridge.py") == "81745864903ab8da78a22fa2ffae0b3bde22191f"
    text = _read("ems_planner_bridge.py")
    assert "def pending_quarter_roll_continuity(" in text
    assert "0 < shift_seconds <= 15 * 60" in text

def test_single_source_execution_controller_owns_physical_behavior() -> None:
    runtime = _read("ems_runtime.py")
    execution = _read("ems_execution.py")
    assert "self.execution = DOEMSExecutionController(hass, entry.entry_id)" in runtime
    assert "DOEMSManualPhysicalExecution" not in runtime
    assert "abs(actual_setpoint - expected_power) > 10" in execution
    assert 'async_stop("planned_energy_reached", emergency=False)' in execution
    assert 'async_stop("device_status_unavailable", emergency=True)' in execution
    assert 'async_stop("battery_power_source_unavailable", emergency=True)' in execution

def test_restart_arm_restore_and_interrupted_run_recovery_are_separate() -> None:
    switch = _read("switch.py")
    execution = _read("ems_execution.py")
    runtime = _read("ems_runtime.py")
    assert "RestoreEntity" in switch
    assert 'previous.attributes.get("mode") == "live_guarded"' in switch
    assert '"mode": "live_guarded"' in switch
    assert 'await self.async_stop("restart_recovery", emergency=True)' in execution
    assert "await self.execution.async_recover_if_needed()" in runtime

def test_manual_execution_is_not_controlled_by_automatic_arm() -> None:
    runtime = _read("ems_runtime.py")
    start = runtime.index("    def _schedule_manual_physical_start")
    end = runtime.index("    @property\n    def control_entity_ids", start)
    block = runtime[start:end]
    manual = block[block.index('        if origin != "manual":'):]
    assert "_automatic_execution_armed" not in manual
    assert "await self.async_execute_selected_plan_verified_handoff()" in manual
    assert "platform_setpoint_handoff_not_confirmed" in manual
    assert "retry_wait:" in manual

def test_revalidation_and_mode_switch_are_owned_by_source_execution() -> None:
    runtime = _read("ems_runtime.py")
    assert "self.execution.evaluate_automatic_handoff(" in runtime
    assert "self.execution.evaluate_final_revalidation(" in runtime
    assert "self.execution.evaluate_mode_switch_transaction(" in runtime
    assert "self.final_revalidation =" not in runtime
    assert "self.mode_switch_preview =" not in runtime

def test_alpha76_service_and_physical_test_surface_is_restored() -> None:
    const = _read("const.py")
    init = _read("__init__.py")
    services = (INTEGRATION / "services.yaml").read_text(encoding="utf-8")
    for service in ("start_charge_test","start_discharge_test","stop_physical_test","execute_selected_plan","stop_execution","schedule_plan","start_plan_now","cancel_plan","stop_all"):
        assert service in const and service in services
    assert "runtime.async_execute_selected_plan_verified_handoff()" in init
    assert "runtime.physical_test.async_start_charge_test(" in init
    assert "runtime.physical_test.async_start_discharge_test(" in init

def test_alpha76_soc_bounds_are_frozen_5_to_100() -> None:
    const = _read("const.py")
    settings = _read("ems_settings.py")
    number = _read("number.py")
    assert "MIN_SOC_PERCENT = 5" in const
    assert "MAX_SOC_PERCENT = 100" in const
    assert "technical_min_soc_percent=MIN_SOC_PERCENT" in settings
    assert "max_soc_percent=MAX_SOC_PERCENT" in settings
    assert 'PlanNumberDefinition("target_soc", "target_soc", "Target SOC", 5, 100' in number

def test_gate_manual_priority_and_alpha76_status_names() -> None:
    path = INTEGRATION / "ems_automatic_execution_gate.py"
    spec = importlib.util.spec_from_file_location("alpha32_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    gate = module.DOEMSAutomaticExecutionGate()
    detail = {"origin":"automatic_72h_planner","purpose":"veiligheidsladen","action":"laden","planner_identity":"id","power_w":300,"target_soc":40,"max_runtime_h":1.0,"all_prices_known":True}
    data = {"scheduler_selected_slot":1,"scheduler_ready":True,"scheduler_slots":{1:detail},"auto_prestart_safe":True,"auto_safety_handoff_safe":True,"auto_execution_handoff_ready":True,"auto_final_revalidation_safe":True,"auto_mode_switch_preview_ready":True,"auto_plan_72h_execution_buffer_safe":True,"forecast_ready":True,"control_path_configured":True,"physical_test_active":False,"execution_active":False}
    ready = gate.evaluate(data, armed=True, readiness={"ready":True})
    assert ready["auto_shadow_status"] == "armed_live_ready"
    assert ready["auto_shadow_execution_permitted"] is True
    manual = dict(data)
    manual["scheduler_slots"] = {1:{**detail,"origin":"manual"}}
    blocked = gate.evaluate(manual, armed=True, readiness={"ready":True})
    assert blocked["auto_shadow_execution_permitted"] is False
    assert "manual_override_active" in blocked["auto_shadow_blockers"]
