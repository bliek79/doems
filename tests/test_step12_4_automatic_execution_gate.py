from __future__ import annotations
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"

def _gate():
    path=INTEGRATION/"ems_automatic_execution_gate.py"
    spec=importlib.util.spec_from_file_location("alpha32_gate_step124",path)
    assert spec is not None and spec.loader is not None
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.DOEMSAutomaticExecutionGate()

def _ready_data(origin: str="automatic_72h_planner") -> dict:
    return {
        "scheduler_selected_slot":1,"scheduler_ready":True,
        "scheduler_slots":{1:{"origin":origin,"purpose":"veiligheidsladen","action":"laden","planner_identity":"id","power_w":300,"target_soc":40,"max_runtime_h":1.0,"all_prices_known":True}},
        "auto_prestart_safe":True,"auto_safety_handoff_safe":True,"auto_execution_handoff_ready":True,
        "auto_final_revalidation_safe":True,"auto_mode_switch_preview_ready":True,
        "auto_plan_72h_execution_buffer_safe":True,"forecast_ready":True,"control_path_configured":True,
        "physical_test_active":False,"execution_active":False,
    }

def test_disarmed_and_armed_states_match_alpha76() -> None:
    disarmed=_gate().evaluate(_ready_data(),armed=False,readiness={"ready":True})
    assert disarmed["auto_shadow_status"]=="ready_disarmed"
    assert disarmed["auto_shadow_execution_permitted"] is False
    armed=_gate().evaluate(_ready_data(),armed=True,readiness={"ready":True})
    assert armed["auto_shadow_status"]=="armed_live_ready"
    assert armed["auto_shadow_execution_permitted"] is True

def test_manual_plan_has_priority_over_automatic_gate() -> None:
    result=_gate().evaluate(_ready_data("manual"),armed=True,readiness={"ready":True})
    assert result["auto_shadow_execution_permitted"] is False
    assert "manual_override_active" in result["auto_shadow_blockers"]
