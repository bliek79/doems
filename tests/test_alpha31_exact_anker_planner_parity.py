from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
from types import SimpleNamespace
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"
START = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)

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


def _input_result(*, soc: float = 10.0) -> tuple[dict, float]:
    rows = []
    for index in range(72):
        start = START + timedelta(hours=index)
        home = 0.03
        solar = 0.0
        import_price = 0.30
        export_price = 0.30
        if index == 0:
            import_price = 0.05
            export_price = 0.05
        if index == 4:
            import_price = 0.70
            export_price = 0.70
        rows.append(
            {
                "start": start.isoformat(),
                "home_kwh": home,
                "solar_kwh": solar,
                "solar_valid": True,
                "import_price": import_price,
                "export_price": export_price,
                "price_source": "test",
                "import_price_source": "test",
                "export_price_source": "test",
            }
        )
    return {
        "status": "ready",
        "native_valid_slot_count": 288,
        "rows": rows,
        "time_contract": {"window_start": START.isoformat()},
    }, soc


def test_alpha31_production_worker_is_exact_adapter_path() -> None:
    _install_stubs()
    adapter = importlib.import_module("custom_components.doems.ems_alpha76_adapter")
    multirate = importlib.import_module("custom_components.doems.ems_multirate")
    input_result, soc = _input_result()

    expected = adapter.run_ems_chain(
        input_result=input_result,
        settings=SETTINGS,
        soc_percent=soc,
        now=START,
    )
    actual = multirate.run_planner_worker(
        input_result=input_result,
        settings=SETTINGS,
        soc_percent=soc,
        reference=START,
    )
    assert actual == expected
    assert actual["ems_policy_source"] == "0.0.1-alpha.76"


def test_alpha31_exact_source_allows_safety_and_profitable_trade_in_same_plan() -> None:
    _install_stubs()
    adapter = importlib.import_module("custom_components.doems.ems_alpha76_adapter")
    input_result, soc = _input_result()
    bundle = adapter.run_ems_chain(
        input_result=input_result,
        settings=SETTINGS,
        soc_percent=soc,
        now=START,
    )

    preview = bundle["planner_preview"]
    plan72 = bundle["plan72"]
    plan = plan72["auto_plan_72h_plan"]

    assert preview["planner_preview_safety_charge_needed"] is True
    assert preview["planner_preview_trade_profitable"] is True
    assert plan72["auto_plan_72h_grid_safety_charge_kwh"] > 0
    assert plan72["auto_plan_72h_grid_trade_charge_kwh"] > 0
    assert plan72["auto_plan_72h_grid_trade_discharge_kwh"] > 0
    assert any(
        "veiligheidsladen" in row["action"] and "handelsladen" in row["action"]
        for row in plan
    )


def test_alpha31_production_multirate_does_not_import_doems_policy_override() -> None:
    source = (INTEGRATION / "ems_multirate.py").read_text(encoding="utf-8")
    assert "ems_policy_alpha20" not in source
    assert "from .ems_alpha76_adapter import SOURCE_TAG, planner_reference, run_ems_chain" in source
