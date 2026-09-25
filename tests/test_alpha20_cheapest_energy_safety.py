from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
from types import SimpleNamespace
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


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
    dt.parse_datetime = lambda value: datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    util.dt = dt
    ha.util = util
    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.util", util)
    sys.modules.setdefault("homeassistant.util.dt", dt)


def _policy():
    _install_stubs()
    return importlib.import_module("custom_components.doems.ems_policy_alpha20")


START = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
SETTINGS = SimpleNamespace(
    battery_capacity_kwh=7.2,
    technical_min_soc_percent=5,
    max_soc_percent=100,
    max_charge_power_w=3200,
    max_discharge_power_w=3200,
    software_reserve_percent=7.0,
    charge_efficiency_percent=92.0,
    discharge_efficiency_percent=92.0,
    minimum_trade_margin_eur_per_kwh=0.10,
    startup_delay_seconds=30,
)


def _run(*, soc: float, home: list[float], solar: list[float], prices: list[float]):
    forecast = []
    for i in range(72):
        forecast.append(
            {
                "time": (START + timedelta(hours=i)).isoformat(),
                "home_consumption_kwh": home[i],
                "solar_kwh": solar[i],
                "solar_forecast_valid": True,
                "price": prices[i],
                "import_price": prices[i],
                "export_price": prices[i],
                "price_source": "test",
                "import_price_source": "test",
                "export_price_source": "test",
            }
        )
    return _policy().build_policy_bundle(
        forecast,
        settings=SETTINGS,
        soc_percent=soc,
        now=START,
    )


def test_alpha20_no_usable_solar_still_keeps_full_horizon_planable() -> None:
    bundle = _run(
        soc=80.0,
        home=[0.15] * 72,
        solar=[0.0] * 72,
        prices=[0.30] * 72,
    )
    assert bundle["energy_need"]["energy_need_valid"] is True
    assert bundle["energy_need"]["energy_need_first_usable_solar"] is None
    assert bundle["planner_preview"]["planner_preview_required_min_soc"] == 12.0
    assert bundle["plan72"]["auto_plan_72h_valid"] is True


def test_alpha20_solar_first_avoids_safety_charge_when_full_route_stays_safe() -> None:
    home = [0.08] * 72
    solar = [0.0] * 72
    for start in (4, 28, 52):
        for i in range(start, start + 6):
            solar[i] = 0.8
    bundle = _run(soc=65.0, home=home, solar=solar, prices=[0.30] * 72)
    assert bundle["planner_preview"]["planner_preview_safety_charge_needed"] is False
    assert bundle["planner_preview"]["planner_preview_safety_charge_hours"] == []
    assert bundle["plan72"]["auto_plan_72h_grid_safety_charge_kwh"] == 0.0


def test_alpha20_later_cheaper_window_wins_if_reachable() -> None:
    home = [0.15] * 72
    solar = [0.0] * 72
    prices = [0.34] * 72
    prices[6] = 0.20
    for i in range(18, 21):
        prices[i] = 0.10
    for i in range(21, 40):
        prices[i] = 0.45
    bundle = _run(soc=60.0, home=home, solar=solar, prices=prices)
    selected = {
        item["time"]
        for item in bundle["planner_preview"]["planner_preview_safety_charge_hours"]
    }
    assert (START + timedelta(hours=18)).isoformat() in selected
    assert (START + timedelta(hours=6)).isoformat() not in selected


def test_alpha20_earlier_bridge_charge_is_used_only_when_needed() -> None:
    home = [0.25] * 72
    solar = [0.0] * 72
    prices = [0.34] * 72
    prices[6] = 0.20
    prices[18] = 0.10
    bundle = _run(soc=25.0, home=home, solar=solar, prices=prices)
    selected = {
        item["time"]
        for item in bundle["planner_preview"]["planner_preview_safety_charge_hours"]
    }
    assert (START + timedelta(hours=6)).isoformat() in selected


def test_alpha20_cheap_window_can_fill_for_later_expensive_period() -> None:
    home = [0.05] * 72
    solar = [0.0] * 72
    prices = [0.40] * 72
    for i in range(18, 21):
        prices[i] = 0.05
    for i in range(21, 31):
        home[i] = 0.60
        prices[i] = 0.48
    bundle = _run(soc=25.0, home=home, solar=solar, prices=prices)
    plan = bundle["plan72"]["auto_plan_72h_plan"]
    assert bundle["plan72"]["auto_plan_72h_grid_safety_charge_kwh"] > 0
    assert max(row["soc_end"] for row in plan) >= 98.0
    assert any("veiligheidsladen" in row["action"] for row in plan)


def test_alpha20_keeps_public_contract_compact_and_g5_frozen() -> None:
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    bridge = (INTEGRATION / "ems_planner_bridge.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    g5 = (INTEGRATION / "ems_g5_live_parity.py").read_text(encoding="utf-8")
    policy = (INTEGRATION / "ems_policy_alpha20.py").read_text(encoding="utf-8")

    assert "from .ems_policy_alpha20 import run_ems_chain" in runtime
    assert 'POLICY_VERSION = "alpha76_baseline_v1"' in g5
    assert "ems_alpha76_adapter" in g5
    assert "grid_support_charge" not in sensor
    assert "Self-Consumption Support Charge" not in sensor
    assert "zelfconsumptie_bijladen" not in bridge
    assert "charge_from_grid_support_kwh" not in bridge
    assert "zelfconsumptie_bijladen" not in policy
    assert "charge_from_grid_support_kwh" not in policy
