"""Integration contracts against the Alpha7.7 Energy/Solar public interfaces."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "doems"

def source(name):
    return (ROOT / name).read_text(encoding="utf-8")

def test_exact_native_forecast_interfaces():
    energy = source("energy_coordinator.py")
    solar = source("solar_forecast.py")
    model = source("solar_forecast_model.py")
    runtime = source("energy_need_runtime.py")
    assert "def forecast(" in energy and "slot.energy_kwh" in runtime
    assert "def points(" in solar and "slot.total_kwh" in runtime
    assert "source_status" in solar and 'self.solar.source_status != "ok"' in runtime
    assert "SOLAR_FORECAST_SLOTS = SOLAR_HORIZON_HOURS * 60 // SOLAR_RESOLUTION_MINUTES" in model
    assert "288" in source("energy_need.py")
    assert "coordinator.async_add_listener(self.refresh)" in runtime
    assert "solar.async_add_listener(self.refresh)" in runtime
    assert "async_track_state_change_event" in runtime
    assert "async_track_time_change" in runtime

def test_all_eleven_named_entities_registered():
    runtime = source("energy_need_runtime.py")
    sensors = source("sensor.py")
    binary = source("binary_sensor.py")
    tree = ast.parse(runtime)
    assignments = [node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "FIELDS" for t in node.targets)]
    assert len(assignments) == 1
    fields = ast.literal_eval(assignments[0].value)
    assert len(fields) == 10 and len({field[0] for field in fields}) == 10
    assert "EnergyNeedSensor(energy_need, field) for field in FIELDS" in sensors
    assert "EnergyNeedValid(runtime)" in binary
    assert "_attr_unique_id = \"doems_ems_energy_need_valid\"" in runtime
    assert '"doems_ems_" + suffix' in runtime

def test_no_physical_action_or_unapproved_defaults():
    runtime = source("energy_need_runtime.py")
    config = source("config_flow.py")
    setup = source("__init__.py")
    for forbidden in ["services.async_call", "async_turn_on", "async_turn_off", "async_set_value"]:
        assert forbidden not in runtime
    assert "CONF_ENERGY_NEED_ENABLED, False" in setup
    assert 'energy_need_requires_energy_and_solar' in config
    assert "CONF_ENERGY_NEED_CAPACITY_KWH, 7.2" not in config
    assert "CONF_ENERGY_NEED_CHARGE_EFFICIENCY, 0.92" not in config
