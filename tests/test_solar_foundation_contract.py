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


def _options():
    return {
        "solar_foundation_enabled": True,
        "solar_location_source": "home_assistant",
        "solar_total_actual_power_entity": "sensor.pv_total",
        "solar_inverter_groups": [
            {"group_id": "inv_a", "name": "Omvormer", "ac_limit_kw": 3.68},
        ],
        "solar_arrays": [
            {"array_id": "arr_n", "name": "Noord", "group_id": "inv_a", "dc_kwp": 2.96, "tilt_deg": 37.0, "azimuth_deg": 0.0, "actual_power_entity": "sensor.pv_north"},
            {"array_id": "arr_s", "name": "Zuid", "group_id": "inv_a", "dc_kwp": 1.48, "tilt_deg": 37.0, "azimuth_deg": 180.0, "actual_power_entity": "sensor.pv_south"},
        ],
    }


def test_generic_1_to_n_topology_is_ready_and_native_contract_stays_fixed() -> None:
    m = _load("solar_foundation_model")
    snapshot = m.build_solar_foundation_snapshot(_options(), ha_latitude=51.0, ha_longitude=5.0)
    assert snapshot["status"] == "ready"
    assert snapshot["inverter_group_count"] == 1
    assert snapshot["array_count"] == 2
    assert snapshot["total_dc_kwp"] == 4.44
    assert snapshot["known_ac_limit_kw"] == 3.68
    assert snapshot["native_time_contract"] == {"resolution_minutes": 15, "horizon_hours": 72, "slot_count": 288}
    assert snapshot["physical_execution_authority"] is False
    assert snapshot["forecast_runtime_active"] is False


def test_labels_do_not_change_stable_topology_signature() -> None:
    m = _load("solar_foundation_model")
    first = _options()
    second = _options()
    second["solar_inverter_groups"][0]["name"] = "Nieuwe naam"
    second["solar_arrays"][0]["name"] = "Andere gebruikersnaam"
    a = m.build_solar_foundation_snapshot(first, ha_latitude=51.0, ha_longitude=5.0)
    b = m.build_solar_foundation_snapshot(second, ha_latitude=51.0, ha_longitude=5.0)
    assert a["topology_signature"] == b["topology_signature"]


def test_geometry_or_stable_identity_changes_signature() -> None:
    m = _load("solar_foundation_model")
    first = _options()
    second = _options()
    second["solar_arrays"][0]["azimuth_deg"] = 15.0
    a = m.build_solar_foundation_snapshot(first, ha_latitude=51.0, ha_longitude=5.0)
    b = m.build_solar_foundation_snapshot(second, ha_latitude=51.0, ha_longitude=5.0)
    assert a["topology_signature"] != b["topology_signature"]


def test_invalid_group_link_and_duplicate_actual_are_blocked() -> None:
    m = _load("solar_foundation_model")
    options = _options()
    options["solar_arrays"][1]["group_id"] = "missing"
    options["solar_arrays"][1]["actual_power_entity"] = "sensor.pv_north"
    blockers = m.validate_solar_foundation(options, ha_latitude=51.0, ha_longitude=5.0)
    assert "array_group_unknown:arr_s" in blockers
    assert "array_actual_duplicate:sensor.pv_north" in blockers
