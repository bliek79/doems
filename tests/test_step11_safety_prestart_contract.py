from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"
def _read(name:str)->str: return (INTEGRATION/name).read_text(encoding="utf-8")

def test_step11_prestart_and_safety_modules_are_alpha76_source_translations() -> None:
    pre=_read("ems_prestart_validator.py"); safety=_read("ems_safety_guard.py")
    assert "class DOEMSPreStartValidator" in pre
    assert "class DOEMSSafetyGuard" in safety
    assert "MIN_SOC_PERCENT <= target_soc <= MAX_SOC_PERCENT" in pre
    assert "MIN_SOC_PERCENT <= target_soc <= MAX_SOC_PERCENT" in safety
    assert ".services.async_call(" not in pre
    assert ".services.async_call(" not in safety

def test_runtime_order_keeps_scheduler_prestart_safety_before_execution() -> None:
    runtime=_read("ems_runtime.py")
    start=runtime.index("async def _async_run_bridge_planstore_scheduler")
    end=runtime.index("    def _schedule_manual_physical_start",start)
    chain=runtime[start:end]
    positions=[
        chain.index("self.scheduler_result = self.scheduler.evaluate("),
        chain.index("refreshed_bridge = build_planner_action_bridge("),
        chain.index("self.prestart_result = self.prestart_validator.evaluate(step11_data)"),
        chain.index("self.safety_result = self.safety_guard.evaluate_automatic_handoff(step11_data)"),
        chain.index("self.execution.evaluate_automatic_handoff("),
        chain.index("self.execution.evaluate_final_revalidation("),
    ]
    assert positions==sorted(positions)
    assert '"physical_test_active": bool(self.physical_test.data.get("active"))' in chain
    assert '"execution_active": bool(self.execution.data.get("active"))' in chain

def test_runtime_observability_reports_real_execution_authority() -> None:
    runtime=_read("ems_runtime.py")
    assert '"automatic_execution_armed": self._automatic_execution_armed' in runtime
    assert '"physical_execution_authority": bool(' in runtime
    assert 'manual_physical.get("active")' in runtime
    assert 'manual_physical.get("auto_mode_switch_active")' in runtime
