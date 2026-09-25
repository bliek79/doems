from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "custom_components" / "doems" / "ems_policy_v2"
PACKAGE = "alpha19_doems_policy_testpkg"


def _install_homeassistant_dt_stub() -> None:
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


def _load(name: str, filename: str):
    _install_homeassistant_dt_stub()
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(POLICY)]
        sys.modules[PACKAGE] = package

    full_name = f"{PACKAGE}.{name}"
    spec = importlib.util.spec_from_file_location(full_name, POLICY / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


const = _load("const", "const.py")
energy_need = _load("energy_need", "energy_need.py")
planner_preview = _load("planner_preview", "planner_preview.py")
planner_72h = _load("planner_72h", "planner_72h.py")


START = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def forecast(*, cheap_support: bool) -> list[dict]:
    rows: list[dict] = []
    for index in range(72):
        price = 0.25
        if cheap_support and index == 4:
            price = 0.05
        elif cheap_support and 9 <= index < 18:
            price = 0.45

        solar = 1.2 if 18 <= index <= 20 else 0.0
        rows.append(
            {
                "time": (START + timedelta(hours=index)).isoformat(),
                "home_consumption_kwh": 0.8,
                "solar_kwh": solar,
                "solar_forecast_valid": True,
                "price": price,
                "import_price": price,
                "export_price": price,
                "price_source": "test",
                "import_price_source": "test",
                "export_price_source": "test",
            }
        )
    return rows


def run_chain(rows: list[dict]) -> tuple[dict, dict, dict]:
    need = energy_need.build_energy_need_analysis(
        rows,
        100.0,
        7.0,
        battery_capacity_kwh=7.2,
        technical_min_soc_percent=5.0,
        max_soc_percent=100.0,
        now=START,
        discharge_efficiency_percent=92.0,
    )
    preview = planner_preview.build_planner_preview(
        rows,
        need,
        100.0,
        92.0,
        92.0,
        0.10,
        max_charge_power_w=3200,
        max_discharge_power_w=3200,
        battery_capacity_kwh=7.2,
        technical_min_soc_percent=5.0,
        max_soc_percent=100.0,
        now=START,
    )
    plan = planner_72h.build_72h_plan_preview(
        rows,
        need,
        preview,
        100.0,
        92.0,
        92.0,
        execution_buffer_percent=2.0,
        max_charge_power_w=3200,
        max_discharge_power_w=3200,
        battery_capacity_kwh=7.2,
        technical_min_soc_percent=5.0,
        max_soc_percent=100.0,
        now=START,
    )
    return need, preview, plan


def test_low_solar_demand_is_context_not_100_percent_hold_floor() -> None:
    need, _preview, plan = run_chain(forecast(cheap_support=False))

    assert need["energy_need_valid"] is True
    assert need["energy_need_until_solar_kwh"] > 7.2
    assert need["energy_need_reserve_enforceable_in_self_consumption"] is False

    first = plan["auto_plan_72h_plan"][0]
    assert first["reserve_floor_soc"] == 12.0
    assert first["execution_reserve_floor_soc"] == 14.0
    assert first["discharge_to_home_kwh"] > 0.0
    assert first["soc_end"] < 100.0
    assert first["planning_need_soc_equivalent"] > first["reserve_floor_soc"]


def test_flat_prices_accept_natural_discharge_to_configured_minimum() -> None:
    _need, preview, plan = run_chain(forecast(cheap_support=False))

    assert preview["planner_preview_support_charge_needed"] is True
    assert preview["planner_preview_support_charge_economic"] is False
    assert preview["planner_preview_support_charge_hours"] == []
    assert round(plan["auto_plan_72h_min_soc"], 1) == 5.0
    assert plan["auto_plan_72h_grid_import_for_home_kwh"] > 0.0
    assert plan["auto_plan_72h_execution_buffer_safe"] is True
    assert plan["auto_plan_72h_execution_buffer_breach_hours"] == 0


def test_cheaper_earlier_window_creates_limited_support_charge() -> None:
    need, preview, plan = run_chain(forecast(cheap_support=True))

    assert need["energy_need_unavoidable_grid_import_kwh"] > 0.0
    assert preview["planner_preview_support_charge_needed"] is True
    assert preview["planner_preview_support_charge_economic"] is True
    assert preview["planner_preview_support_charge_kwh"] > 0.0
    assert preview["planner_preview_support_expected_savings_eur"] > 0.0
    assert plan["auto_plan_72h_grid_support_charge_kwh"] > 0.0
    assert any(
        "zelfconsumptie_bijladen" in row["action"]
        for row in plan["auto_plan_72h_plan"]
    )


def test_production_runtime_uses_v2_while_g5_keeps_frozen_alpha76() -> None:
    runtime = (ROOT / "custom_components" / "doems" / "ems_runtime.py").read_text(encoding="utf-8")
    g5 = (ROOT / "custom_components" / "doems" / "ems_g5_live_parity.py").read_text(encoding="utf-8")
    bridge = (ROOT / "custom_components" / "doems" / "ems_planner_bridge.py").read_text(encoding="utf-8")

    assert "from .ems_policy_adapter import run_ems_chain" in runtime
    assert "from .ems_alpha76.energy_need import build_energy_need_analysis" in g5
    assert "from .ems_alpha76_adapter import (" in g5
    assert 'row.get("charge_from_grid_support_kwh")' in bridge
    assert '"zelfconsumptie_bijladen"' in bridge
