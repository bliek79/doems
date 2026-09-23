from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_plan72_observability_parity_sensor_exists() -> None:
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    assert "class DOEMSEMSPlan72Sensor" in sensor
    assert "def build_plan72_sensors" in sensor
    assert 'attrs["plan"] = data.get("auto_plan_72h_plan", [])' in sensor
    assert '_unrecorded_attributes = frozenset({"plan"})' in sensor
    assert 'f"doems_ems_plan72_{suffix}"' in sensor


def test_plan72_observability_copies_source_summary_contract() -> None:
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    for token in (
        "auto_plan_72h_status",
        "auto_plan_72h_count",
        "auto_plan_72h_end_soc",
        "auto_plan_72h_min_soc",
        "auto_plan_72h_reserve_floor_soc",
        "auto_plan_72h_dynamic_reserve_max_soc",
        "auto_plan_72h_execution_reserve_floor_soc",
        "auto_plan_72h_min_execution_headroom_soc",
        "auto_plan_72h_execution_buffer_breach_hours",
        "auto_plan_72h_solar_horizon_complete",
        "auto_plan_72h_solar_horizon_incomplete_hours",
        "auto_plan_72h_solar_charge_kwh",
        "auto_plan_72h_grid_safety_charge_kwh",
        "auto_plan_72h_grid_trade_charge_kwh",
        "auto_plan_72h_home_discharge_kwh",
        "auto_plan_72h_grid_trade_discharge_kwh",
    ):
        assert token in sensor


def test_plan72_hours_exposes_dashboard_fields_already_computed_by_planner() -> None:
    planner = (INTEGRATION / "ems_alpha76" / "planner_72h.py").read_text(encoding="utf-8")
    for token in (
        '"time": hour.isoformat()',
        '"price": row["import_price"]',
        '"price_source": row["price_source"]',
        '"solar_kwh": round(solar, 3)',
        '"home_consumption_kwh": round(home, 3)',
        '"charge_from_solar_kwh": round(solar_charge_input, 3)',
        '"charge_from_grid_safety_kwh": round(grid_safety_input, 3)',
        '"charge_from_grid_trade_kwh": round(grid_trade_input, 3)',
        '"discharge_to_home_kwh": round(discharge_to_home, 3)',
        '"discharge_to_grid_kwh": round(discharge_to_grid, 3)',
        '"soc_start": round(float(soc_start), 1)',
        '"soc_end": round(soc_end, 1)',
        '"reserve_floor_soc": round(reserve_floor_end_soc, 1)',
        '"execution_reserve_floor_soc": round(execution_floor_end_soc, 1)',
        '"execution_headroom_soc": round(execution_headroom_soc, 1)',
        '"action": "+".join(action_parts)',
    ):
        assert token in planner


def test_plan72_observability_does_not_change_physical_boundary() -> None:
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in sensor
    assert '"automatic_execution_armed": self._automatic_execution_armed' in runtime
    assert '"service_calls_performed": False' in runtime
    assert '"physical_execution_authority": False' in runtime


def test_plan72_solar_horizon_uses_clear_single_sensor_contract() -> None:
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    planner = (INTEGRATION / "ems_alpha76" / "planner_72h.py").read_text(encoding="utf-8")
    adapter = (INTEGRATION / "ems_alpha76_adapter.py").read_text(encoding="utf-8")
    input_contract = (INTEGRATION / "ems_input_contract.py").read_text(encoding="utf-8")

    # No extra public horizon sensors are introduced: the existing sensor gets
    # clearer state semantics and compact diagnostics as attributes.
    assert '("solar_horizon_status", "DOEMS EMS Plan72 Solar Horizon"' in sensor
    assert '"auto_plan_72h_solar_horizon_status") or "no_data"' in sensor
    for token in (
        '"forecast_coverage_hours"',
        '"forecast_missing_hours"',
        '"forecast_coverage_percent"',
        '"forecast_complete"',
        '"next_usable_solar_available"',
        '"next_usable_solar"',
        '"hours_until_next_usable_solar"',
        '"last_usable_solar"',
        '"plan_start"',
        '"plan_end"',
        '"hours_after_last_usable_solar"',
        '"lookahead_limited_by_plan_end"',
        '"reason"',
    ):
        assert token in sensor

    assert '"solar_valid": solar_valid' in input_contract
    assert '"solar_forecast_valid": bool(raw.get("solar_valid"))' in adapter
    assert '"auto_plan_72h_solar_horizon_status": solar_horizon_status' in planner
    assert '"auto_plan_72h_solar_forecast_coverage_hours"' in planner
    assert '"auto_plan_72h_next_usable_solar"' in planner
    assert '"auto_plan_72h_hours_after_last_usable_solar"' in planner
    assert '"auto_plan_72h_lookahead_limited_by_plan_end"' in planner
    assert 'solar_horizon_status = "ready"' in planner
    assert 'solar_horizon_status = "limited"' in planner
    assert 'solar_horizon_status = "no_data"' in planner


def test_plan72_solar_horizon_keeps_physical_scope_unchanged() -> None:
    planner = (INTEGRATION / "ems_alpha76" / "planner_72h.py").read_text(encoding="utf-8")
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in planner
    assert ".services.async_call(" not in sensor
