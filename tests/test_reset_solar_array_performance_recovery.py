"""Regression: recover the proven Alpha25 per-array Solar factor in DOEMS reset."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import json
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


def _options(ac_limit_kw=10.0):
    return {
        "solar_foundation_enabled": True,
        "solar_location_source": "home_assistant",
        "solar_inverter_groups": [
            {"group_id": "sma", "name": "SMA", "ac_limit_kw": ac_limit_kw},
        ],
        "solar_arrays": [
            {"array_id": "north", "name": "Noord", "group_id": "sma",
             "dc_kwp": 2.96, "tilt_deg": 32.0, "azimuth_deg": 0.0},
            {"array_id": "south", "name": "Zuid", "group_id": "sma",
             "dc_kwp": 1.48, "tilt_deg": 25.0, "azimuth_deg": 180.0},
        ],
    }


def test_legacy_options_keep_per_array_090_default_and_calculation() -> None:
    foundation = _load("solar_foundation_model")
    model = _load("solar_forecast_model")
    snapshot = foundation.build_solar_foundation_snapshot(
        _options(), ha_latitude=51.0, ha_longitude=5.0
    )
    assert snapshot["status"] == "ready"
    assert snapshot["schema_version"] == 2
    assert snapshot["default_performance_factor"] == 0.90
    assert [item["performance_factor"] for item in snapshot["arrays"]] == [0.90, 0.90]
    point = model.build_forecast_point(
        snapshot,
        start=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc),
        irradiance_by_array={"north": 1000.0, "south": 1000.0},
    )
    assert point.array_kw == (2.664, 1.332)
    assert point.total_kw == 3.996
    assert point.total_kwh == 0.999


def test_82_67_per_array_yield_is_applied_before_ac_cap() -> None:
    foundation = _load("solar_foundation_model")
    model = _load("solar_forecast_model")
    options = _options()
    options["solar_arrays"][0]["performance_factor"] = 0.82
    options["solar_arrays"][1]["performance_factor"] = 0.67
    snapshot = foundation.build_solar_foundation_snapshot(
        options, ha_latitude=51.0, ha_longitude=5.0
    )
    assert [item["performance_factor"] for item in snapshot["arrays"]] == [0.82, 0.67]
    point = model.build_forecast_point(
        snapshot,
        start=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc),
        irradiance_by_array={"north": 1000.0, "south": 1000.0},
    )
    assert point.array_kw == (2.4272, 0.9916)
    assert point.total_kw == 3.4188
    assert point.array_kwh == (0.6068, 0.2479)
    assert point.total_kwh == 0.8547


def test_ac_group_clipping_proportion_stays_unchanged() -> None:
    model = _load("solar_forecast_model")
    options = _options(ac_limit_kw=1.2)
    for item in options["solar_arrays"]:
        item["dc_kwp"] = 1.0
    options["solar_arrays"][0]["performance_factor"] = 1.0
    options["solar_arrays"][1]["performance_factor"] = 0.5
    point = model.build_forecast_point(
        {"arrays": options["solar_arrays"], "inverter_groups": options["solar_inverter_groups"]},
        start=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc),
        irradiance_by_array={"north": 1000.0, "south": 1000.0},
    )
    assert point.clipped_groups == ("sma",)
    assert point.array_kw == (0.8, 0.4)
    assert point.total_kw == 1.2


def test_factor_persists_in_foundation_and_changes_topology_signature() -> None:
    foundation = _load("solar_foundation_model")
    a = _options()
    b = _options()
    b["solar_arrays"][0]["performance_factor"] = 0.82
    b["solar_arrays"][1]["performance_factor"] = 0.67
    snap_a = foundation.build_solar_foundation_snapshot(a, ha_latitude=51.0, ha_longitude=5.0)
    snap_b = foundation.build_solar_foundation_snapshot(b, ha_latitude=51.0, ha_longitude=5.0)
    assert snap_a["topology_signature"] != snap_b["topology_signature"]
    assert [item["array_id"] for item in snap_b["arrays"]] == ["north", "south"]
    b["solar_arrays"][0]["name"] = "Noord hernoemd"
    renamed = foundation.build_solar_foundation_snapshot(b, ha_latitude=51.0, ha_longitude=5.0)
    assert renamed["topology_signature"] == snap_b["topology_signature"]


def test_invalid_factor_is_blocked() -> None:
    foundation = _load("solar_foundation_model")
    for factor in (-0.01, 1.01, "invalid"):
        options = _options()
        options["solar_arrays"][0]["performance_factor"] = factor
        blockers = foundation.validate_solar_foundation(
            options, ha_latitude=51.0, ha_longitude=5.0
        )
        assert "array_performance_factor_invalid:north" in blockers


def test_native_288_slots_remain_exact_with_mixed_factors() -> None:
    model = _load("solar_forecast_model")
    options = _options()
    options["solar_arrays"][0]["performance_factor"] = 0.82
    options["solar_arrays"][1]["performance_factor"] = 0.67
    first = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    times = [first + timedelta(minutes=15 * i) for i in range(288)]
    result = model.build_forecast_timeline(
        {"arrays": options["solar_arrays"], "inverter_groups": options["solar_inverter_groups"]},
        starts=times,
        irradiance_by_array={
            "north": {t: 500.0 for t in times},
            "south": {t: 500.0 for t in times},
        },
    )
    assert len(result) == 288
    assert result[-1].start == first + timedelta(hours=71, minutes=45)
    assert result[0].array_kw == (1.2136, 0.4958)
    assert result[0].array_ids == ("north", "south")


def test_ui_storage_and_mixed_diagnostics_contract() -> None:
    config = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "solar_forecast.py").read_text(encoding="utf-8")
    model = (INTEGRATION / "solar_forecast_model.py").read_text(encoding="utf-8")
    storage = (INTEGRATION / "solar_foundation.py").read_text(encoding="utf-8")
    assert '"performance_factor_percent"' in config
    assert '"performance_factor": round(float(user_input["performance_factor_percent"]) / 100.0, 6)' in config
    assert 'existing.get("performance_factor", SOLAR_DEFAULT_PERFORMANCE_FACTOR)' in config
    assert 'array.get("performance_factor", SOLAR_PERFORMANCE_FACTOR)' in model
    assert "performance_factor=SOLAR_PERFORMANCE_FACTOR" not in runtime
    assert '"array_performance_factors": array_performance_factors' in runtime
    assert '"performance_factor_semantics": "static_per_array_before_group_ac_cap"' in runtime
    assert '"mixed" if unique_factors else SOLAR_PERFORMANCE_FACTOR' in runtime
    assert "self.store.async_save(self.snapshot)" in storage
    for name in ("strings.json", "translations/nl.json", "translations/en.json"):
        labels = json.loads((INTEGRATION / name).read_text(encoding="utf-8"))
        assert "(%)" in labels["options"]["step"]["solar_array"]["data"]["performance_factor_percent"]


def test_shading_is_not_part_of_static_performance_factor() -> None:
    model = (INTEGRATION / "solar_forecast_model.py").read_text(encoding="utf-8")
    assert "shading_learning" not in model
    assert "obstruction_learning" not in model
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    assert "SOLAR_DEFAULT_PERFORMANCE_FACTOR = 0.90" in const
