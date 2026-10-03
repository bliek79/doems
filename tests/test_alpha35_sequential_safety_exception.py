from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"
START = datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)


def _install_stubs() -> None:
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    if "custom_components.doems.ems_alpha76" not in sys.modules:
        package = types.ModuleType("custom_components.doems.ems_alpha76")
        package.__path__ = [str(INTEGRATION / "ems_alpha76")]
        sys.modules["custom_components.doems.ems_alpha76"] = package

    ha = types.ModuleType("homeassistant")
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")
    dt.UTC = timezone.utc
    dt.DEFAULT_TIME_ZONE = timezone.utc
    dt.utcnow = lambda: datetime.now(timezone.utc)
    dt.now = lambda: datetime.now(timezone.utc)
    dt.parse_datetime = lambda value: datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    util.dt = dt
    ha.util = util
    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.util", util)
    sys.modules.setdefault("homeassistant.util.dt", dt)


def _blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _forecast() -> list[dict]:
    rows = []
    usable_solar = {4, 5, 20, 21, 44, 45}
    cheap = {1, 2, 6, 7, 8, 9, 12, 13}
    for index in range(72):
        start = START + timedelta(hours=index)
        price = 0.08 if index in cheap else 0.30
        rows.append(
            {
                "time": start.isoformat(),
                "home_consumption_kwh": 0.45,
                "solar_kwh": 0.90 if index in usable_solar else 0.0,
                "price": price,
                "import_price": price,
                "export_price": price,
                "price_source": "test",
                "import_price_source": "test",
                "export_price_source": "test",
            }
        )
    return rows


def _preview() -> dict:
    return {
        "planner_preview_safety_charge_hours": [],
        "planner_preview_trade_profitable": False,
        "planner_preview_best_charge_time": None,
        "planner_preview_best_discharge_time": None,
        "planner_preview_best_discharge_price": None,
        "planner_preview_best_charge_price": None,
        "planner_preview_minimum_trade_margin": 0.10,
    }


def test_alpha35_keeps_frozen_alpha76_planner_as_reference() -> None:
    assert _blob_sha(INTEGRATION / "ems_alpha76" / "planner_72h.py") == "d9cd3bb306da5f7e608d558a2b28d7366931e29b"
    adapter = (INTEGRATION / "ems_alpha76_adapter.py").read_text(encoding="utf-8")
    assert "build_72h_plan_preview_sequential_safety" in adapter
    assert "alpha35_sequential_safety_exception_v1" in adapter


def test_sequential_safety_replay_fixes_intervening_home_consumption_gap() -> None:
    _install_stubs()
    old = importlib.import_module("custom_components.doems.ems_alpha76.planner_72h")
    fixed = importlib.import_module(
        "custom_components.doems.ems_alpha76.planner_72h_sequential_safety"
    )
    kwargs = {
        "forecast": _forecast(),
        "energy_need": {"energy_need_safety_reserve_kwh": 0.504},
        "planner_preview": _preview(),
        "soc": 55.0,
        "charge_efficiency_percent": 92.0,
        "discharge_efficiency_percent": 92.0,
        "execution_buffer_percent": 2.0,
        "max_charge_power_w": 3200,
        "max_discharge_power_w": 3200,
        "now": START,
    }
    original = old.build_72h_plan_preview(**kwargs)
    corrected = fixed.build_72h_plan_preview_sequential_safety(**kwargs)

    assert original["auto_plan_72h_execution_buffer_breach_hours"] > 0
    assert original["auto_plan_72h_execution_buffer_safe"] is False

    assert corrected["auto_plan_72h_status"] == "ready"
    assert corrected["auto_plan_72h_valid"] is True
    assert corrected["auto_plan_72h_execution_buffer_breach_hours"] == 0
    assert corrected["auto_plan_72h_execution_buffer_safe"] is True
    assert corrected["auto_plan_72h_safety_plan_authority"] == (
        "doems_sequential_safety_exception_v1"
    )
    assert corrected["auto_plan_72h_safety_plan_replay_count"] > 1
    assert corrected["auto_plan_72h_safety_plan_unmet_deadlines"] == []

    for row in corrected["auto_plan_72h_plan"]:
        assert row["soc_end"] + 0.05 >= row["execution_reserve_floor_soc"]


def test_infeasible_execution_reserve_fails_closed_instead_of_green_valid() -> None:
    _install_stubs()
    fixed = importlib.import_module(
        "custom_components.doems.ems_alpha76.planner_72h_sequential_safety"
    )
    forecast = _forecast()
    # Force a future reserve demand that cannot be restored: no charge power.
    result = fixed.build_72h_plan_preview_sequential_safety(
        forecast,
        {"energy_need_safety_reserve_kwh": 0.504},
        _preview(),
        20.0,
        92.0,
        92.0,
        execution_buffer_percent=2.0,
        max_charge_power_w=0,
        max_discharge_power_w=3200,
        now=START,
    )
    assert result["auto_plan_72h_valid"] is False
    assert result["auto_plan_72h_status"] == "infeasible"
    assert result["auto_plan_72h_execution_buffer_safe"] is False
    assert result["auto_plan_72h_first_execution_breach"] is not None
