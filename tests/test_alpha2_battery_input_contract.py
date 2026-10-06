from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load(name: str):
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    return importlib.import_module(f"custom_components.doems.{name}")


def _ready_sources():
    return {
        "soc": {"entity_id": "sensor.battery_soc", "state": "34", "unit": "%"},
        "capacity": {"entity_id": "sensor.battery_capacity", "state": "7.1", "unit": "kWh"},
        "charge_power": {"entity_id": "sensor.battery_charge", "state": "0", "unit": "W"},
        "discharge_power": {"entity_id": "sensor.battery_discharge", "state": "2510", "unit": "W"},
        "device_status": {"entity_id": "sensor.battery_status", "state": "discharging", "unit": None},
    }


def test_alpha2_ready_contract_uses_live_capacity_without_fallback() -> None:
    m = _load("battery_contract_model")
    result = m.evaluate_battery_input_contract(_ready_sources())
    assert result["status"] == "ready"
    assert result["ready_for_soc_projection"] is True
    assert result["soc_percent"] == 34.0
    assert result["capacity_kwh"] == 7.1
    assert result["charge_power_w"] == 0.0
    assert result["discharge_power_w"] == 2510.0
    assert result["device_status"] == "discharging"
    assert result["read_only"] is True
    assert result["physical_execution_authority"] is False
    assert result["blockers"] == []


def test_alpha2_missing_capacity_blocks_and_never_uses_nominal_fallback() -> None:
    m = _load("battery_contract_model")
    sources = _ready_sources()
    sources["capacity"] = {"entity_id": "sensor.battery_capacity", "state": "unavailable", "unit": "kWh"}
    result = m.evaluate_battery_input_contract(sources)
    assert result["status"] == "blocked"
    assert result["ready_for_soc_projection"] is False
    assert result["capacity_kwh"] is None
    assert "capacity_source_unavailable" in result["blockers"]


def test_alpha2_simultaneous_charge_discharge_is_fail_closed() -> None:
    m = _load("battery_contract_model")
    sources = _ready_sources()
    sources["charge_power"]["state"] = "500"
    result = m.evaluate_battery_input_contract(sources)
    assert result["status"] == "blocked"
    assert result["direction_consistent"] is False
    assert "simultaneous_charge_and_discharge" in result["blockers"]


def test_alpha2_capacity_and_power_normalization() -> None:
    m = _load("battery_contract_model")
    assert m.normalize_capacity_kwh("7100", "Wh") == 7.1
    assert m.normalize_capacity_kwh("7.1", "kWh") == 7.1
    assert m.normalize_positive_power_w("2.5", "kW") == 2500.0
    assert m.normalize_soc_percent("34", "%") == 34.0


def test_alpha2_install_surface_is_configurable_and_not_anker_hardcoded() -> None:
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    flow = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    init = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")

    for token in (
        "battery_observation_enabled",
        "battery_soc_entity",
        "battery_capacity_entity",
        "battery_charge_power_entity",
        "battery_discharge_power_entity",
        "battery_status_entity",
    ):
        assert token in const + flow

    assert "DOEMSBatteryInputContract" in init
    assert "DOEMSBatteryInputStatusSensor" in sensor
    assert "doems_battery_input_status" in sensor

    active = "\n".join(
        path.read_text(encoding="utf-8")
        for path in INTEGRATION.rglob("*.py")
    )
    assert "anker_solix_solarbank_max_ac_185" not in active
    assert '"physical_execution_authority": False' in active


def test_alpha2_1_battery_observation_reuses_existing_power_sources() -> None:
    flow = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    assert "def _battery_power_sources_reusable" in flow
    assert "reuse_power_sources = self._battery_power_sources_reusable()" in flow
    assert "if not reuse_power_sources:" in flow
    assert "schema: dict[vol.Marker, Any]" in flow
    # The flow must only add charge/discharge selectors when no valid Energy
    # battery-power sources are already available.
    observation = flow.split("async def async_step_battery_observation", 1)[1]
    observation = observation.split("async def async_step_solar_system", 1)[0]
    assert observation.count("CONF_BATTERY_CHARGE_POWER_ENTITY") >= 2
    assert observation.count("CONF_BATTERY_DISCHARGE_POWER_ENTITY") >= 2
    assert "if not reuse_power_sources:" in observation
