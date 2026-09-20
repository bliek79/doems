from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load_pure(name: str):
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    return importlib.import_module(f"custom_components.doems.{name}")


def test_soc_parser_is_fail_closed() -> None:
    m = _load_pure("ems_soc")
    assert m.parse_soc_percent("47.5") == 47.5
    assert m.parse_soc_percent(0) == 0.0
    assert m.parse_soc_percent(100) == 100.0
    for value in (None, "unknown", "unavailable", "", "abc", -0.1, 100.1):
        assert m.parse_soc_percent(value) is None


def test_soc_source_is_optional_generic_and_read_only() -> None:
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    flow = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert 'CONF_SOC_ENTITY = "soc_entity"' in const
    assert "_optional_entity(CONF_SOC_ENTITY" in flow
    assert "unsupported_soc_unit" in flow
    assert "doems_source_not_allowed" in flow
    assert "async_track_state_change_event" in runtime
    assert ".services.async_call(" not in runtime


def test_live_shadow_runtime_uses_existing_doems_forecast_and_alpha76_chain() -> None:
    init = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "ems_shadow_runtime.py").read_text(encoding="utf-8")
    live = (INTEGRATION / "ems_live_input.py").read_text(encoding="utf-8")
    assert "DOEMSEMSShadowRuntime" in init
    assert "await ems_shadow.async_setup()" in init
    assert "build_live_ems_input(" in runtime
    assert "run_shadow_chain(" in runtime
    assert 'coordinator.forecast(now=reference)' in live
    assert 'solar_forecast.points' in live
    assert 'prices.price_window(window_start=window_start, slot_count=288)' in live
    assert 'prices.timeline_slots' not in live
    assert '"input_source": "existing_doems_forecast"' in live


def test_live_shadow_runtime_waits_fail_closed_for_missing_inputs() -> None:
    runtime = (INTEGRATION / "ems_shadow_runtime.py").read_text(encoding="utf-8")
    for status in (
        "waiting_for_soc_source",
        "waiting_for_valid_soc",
        "waiting_for_forecast_components",
        "waiting_for_complete_forecast",
    ):
        assert status in runtime
    assert 'input_result.get("native_valid_slot_count") != 288' in runtime
    assert 'len(input_result.get("rows") or []) != 72' in runtime


def test_shadow_diagnostic_sensor_is_compact_and_non_actuating() -> None:
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert "class DOEMSEMSShadowSensor" in sensor
    assert 'doems_ems_shadow' in sensor
    assert '"shadow_planner_runtime_active": True' in runtime
    assert '"startup_delay_runtime_gate_active": False' in runtime
    assert '"shadow_plan_store_active": True' in runtime
    assert '"scheduler_invoked": bool(self.scheduler_result)' in runtime
    assert '"prestart_validator_invoked": False' in runtime
    assert '"execution_controller_invoked": False' in runtime
    assert '"service_calls_performed": False' in runtime
    assert '"physical_execution_authority": False' in runtime
    for field in ("invalid_slot_count","first_invalid_slot","last_invalid_slot","invalid_slots"):
        assert f'"{field}"' in runtime
    assert '"auto_plan_72h_plan"' not in runtime
