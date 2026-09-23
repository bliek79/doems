from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"

def _load_input_contract():
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    return importlib.import_module("custom_components.doems.ems_input_contract")


def _slots(start: datetime):
    energy=[]; solar=[]; prices=[]
    for i in range(288):
        t=start+timedelta(minutes=15*i)
        energy.append({"start":t,"energy_kwh":0.1})
        solar.append({"start":t,"total_kwh":0.05})
        prices.append({"time":t,"import_all_in":0.2+i/100000,"export_all_in":0.1+i/100000,"kind":"known_pt15m"})
    return energy,solar,prices


def test_alpha41_mapping_is_exact_288_to_72_and_keeps_quarter_offset():
    start=datetime(2026,9,20,10,15,tzinfo=timezone.utc)
    energy,solar,prices=_slots(start)
    result=_load_input_contract().build_alpha41_transport_input(
        window_start=start,energy_slots=energy,solar_slots=solar,price_slots=prices
    )
    assert result["status"]=="ready"
    assert len(result["slots"])==288
    assert len(result["rows"])==72
    assert result["native_valid_slot_count"]==288
    assert result["rows"][0]["start"]==start.isoformat()
    assert result["rows"][0]["end"]==(start+timedelta(hours=1)).isoformat()
    assert result["rows"][0]["home_kwh"]==0.4
    assert result["rows"][0]["solar_kwh"]==0.2
    assert result["time_contract"]["alignment_policy"]=="alpha41_rolling_quarter_start_no_clock_hour_rounding"


def test_missing_native_quarter_blocks_only_its_transport_row():
    start=datetime(2026,9,20,10,30,tzinfo=timezone.utc)
    energy,solar,prices=_slots(start)
    solar.pop(7)
    result=_load_input_contract().build_alpha41_transport_input(
        window_start=start,energy_slots=energy,solar_slots=solar,price_slots=prices
    )
    assert result["status"]=="partial"
    assert result["native_valid_slot_count"]==287
    assert result["rows"][1]["fully_valid"] is False
    assert result["rows"][0]["fully_valid"] is True
    assert result["rows"][2]["fully_valid"] is True


def test_alpha8_uses_existing_doems_forecast_and_independent_planning_runtime():
    live=(INTEGRATION/"ems_live_input.py").read_text(encoding="utf-8")
    adapter=(INTEGRATION/"ems_alpha76_adapter.py").read_text(encoding="utf-8")
    assert 'coordinator.forecast(now=reference)' in live
    assert 'solar_forecast.points' in live
    assert 'prices.price_window(window_start=window_start, slot_count=288)' in live
    assert '"input_source": "existing_doems_forecast"' in live
    assert '"planner_runtime_active": False' in live
    assert '"physical_execution_authority": False' in live
    assert 'run_ems_chain' in adapter
    assert '"plan_store_write": True' in adapter
    assert '"scheduler_invoked": True' in adapter
    assert '"service_calls_performed": False' in adapter


def test_all_static_settings_are_consumed_by_frozen_decision_functions():
    adapter=(INTEGRATION/"ems_alpha76_adapter.py").read_text(encoding="utf-8")
    for field in (
        "battery_capacity_kwh","technical_min_soc_percent","max_soc_percent",
        "max_charge_power_w","max_discharge_power_w","software_reserve_percent",
        "charge_efficiency_percent","discharge_efficiency_percent",
        "minimum_trade_margin_eur_per_kwh",
    ):
        assert f"settings.{field}" in adapter
    assert "settings.startup_delay_seconds" not in adapter
    assert '"startup_delay_runtime_gate_active": False' in adapter


def test_solar_coverage_is_tracked_independently_from_other_inputs():
    start=datetime(2026,9,23,3,30,tzinfo=timezone.utc)
    energy,solar,prices=_slots(start)

    # Missing a price quarter must not make an otherwise complete solar hour
    # look like missing solar forecast coverage.
    prices.pop(1)
    result=_load_input_contract().build_alpha41_transport_input(
        window_start=start,energy_slots=energy,solar_slots=solar,price_slots=prices
    )
    assert result["rows"][0]["fully_valid"] is False
    assert result["rows"][0]["solar_valid"] is True
    assert result["rows"][0]["solar_kwh"]==0.2


def test_missing_solar_quarter_marks_only_solar_coverage_missing():
    start=datetime(2026,9,23,3,30,tzinfo=timezone.utc)
    energy,solar,prices=_slots(start)
    solar.pop(1)
    result=_load_input_contract().build_alpha41_transport_input(
        window_start=start,energy_slots=energy,solar_slots=solar,price_slots=prices
    )
    assert result["rows"][0]["solar_valid"] is False
    assert result["rows"][0]["solar_kwh"] is None
