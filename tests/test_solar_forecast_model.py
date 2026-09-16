from __future__ import annotations

from datetime import datetime, timezone
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


def _foundation(ac_limit_kw: float = 3.68):
    return {
        "status": "ready",
        "enabled": True,
        "inverter_groups": [
            {"group_id": "inv_a", "name": "SMA SB3.6", "ac_limit_kw": ac_limit_kw},
        ],
        "arrays": [
            {"array_id": "arr_n", "name": "Noord", "group_id": "inv_a", "dc_kwp": 2.96, "tilt_deg": 37.0, "azimuth_deg": 0.0},
            {"array_id": "arr_s", "name": "Zuid", "group_id": "inv_a", "dc_kwp": 1.48, "tilt_deg": 37.0, "azimuth_deg": 180.0},
        ],
    }


def test_azimuth_adapter_matches_alpha41_open_meteo_convention() -> None:
    m = _load("solar_forecast_model")
    assert m.canonical_to_open_meteo_azimuth(0) == 180.0
    assert m.canonical_to_open_meteo_azimuth(90) == -90.0
    assert m.canonical_to_open_meteo_azimuth(180) == 0.0
    assert m.canonical_to_open_meteo_azimuth(270) == 90.0


def test_group_ac_limit_clips_group_sum_not_each_array_independently() -> None:
    m = _load("solar_forecast_model")
    point = m.build_forecast_point(
        _foundation(ac_limit_kw=3.0),
        start=datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc),
        irradiance_by_array={"arr_n": 1000.0, "arr_s": 1000.0},
    )
    assert point.total_kw == 3.0
    assert point.clipped_groups == ("inv_a",)
    assert round(sum(point.array_kw), 6) == 3.0
    # proportional clipping preserves the 2:1 DC-capacity relationship
    assert point.array_kw == (2.0, 1.0)
    assert point.total_kwh == 0.75


def test_timeline_fails_closed_when_one_array_slot_is_missing() -> None:
    m = _load("solar_forecast_model")
    start = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    try:
        m.build_forecast_timeline(
            _foundation(),
            starts=[start],
            irradiance_by_array={"arr_n": {start: 100.0}, "arr_s": {}},
        )
    except ValueError as err:
        assert str(err).startswith("irradiance_missing:arr_s")
    else:
        raise AssertionError("missing array slot must block timeline construction")


def test_native_p31_contract_is_15_minutes_72_hours_288_slots() -> None:
    m = _load("solar_forecast_model")
    assert m.SOLAR_RESOLUTION_MINUTES == 15
    assert m.SOLAR_HORIZON_HOURS == 72
    assert m.SOLAR_FORECAST_SLOTS == 288
    assert m.SOLAR_FORECAST_MODEL == "open_meteo_gti_physical_v0.1"
    assert m.SOLAR_PERFORMANCE_FACTOR == 0.90
