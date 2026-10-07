from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _axis(
    *,
    start: datetime | None = None,
    home: float = 0.0,
    solar: float = 0.0,
    imp: float = 0.30,
    exp: float = 0.10,
):
    start = start or datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)
    energy = []
    pv = []
    prices = {}
    for index in range(288):
        slot = start + timedelta(minutes=15 * index)
        end = slot + timedelta(minutes=15)
        energy.append(
            {
                "start": slot.isoformat(),
                "end": end.isoformat(),
                "home_kwh": home,
            }
        )
        pv.append({"start": slot.isoformat(), "solar_kwh": solar})
        prices[slot.isoformat()] = {
            "time": slot.isoformat(),
            "import_all_in": imp,
            "export_all_in": exp,
            "kind": "known_15m",
        }
    return energy, pv, prices


def test_alpha63_usable_solar_reconstructs_two_full_clock_hours() -> None:
    m = _load("automatic_planner_model")
    start = datetime(2026, 10, 7, 0, 15, tzinfo=timezone.utc)
    energy, solar, _prices = _axis(start=start)

    # The first partial clock hour must not qualify.
    for index in range(3):
        energy[index]["home_kwh"] = 0.01
        solar[index]["solar_kwh"] = 0.20

    # 01:00-02:00 and 02:00-03:00 each have solar == home in total,
    # but individual quarters do not all satisfy solar >= home.
    for base in (3, 7):
        for offset in range(4):
            energy[base + offset]["home_kwh"] = 0.10
        solar[base + 0]["solar_kwh"] = 0.20
        solar[base + 1]["solar_kwh"] = 0.20
        solar[base + 2]["solar_kwh"] = 0.00
        solar[base + 3]["solar_kwh"] = 0.00

    axis, blockers = m._validate_time_axis(energy, solar)
    assert blockers == []
    pairs = m._usable_solar_pairs(axis)
    assert pairs
    assert pairs[0]["first_index"] == 3
    assert pairs[0]["start"] == datetime(
        2026, 10, 7, 1, 0, tzinfo=timezone.utc
    )


def test_alpha63_incomplete_solar_horizon_falls_back_to_base_floor() -> None:
    m = _load("automatic_planner_model")
    energy, solar, prices = _axis(home=0.02, solar=0.0)
    result = m.build_automatic_plan(
        energy_slots=energy,
        solar_slots=solar,
        plans=[],
        start_soc_percent=50,
        capacity_kwh=7.1,
        price_by_start=prices,
    )
    assert result["valid"] is True
    assert result["planner_floor_soc_percent"] == 10.0
    assert result["dynamic_reserve_start_soc_percent"] == 10.0
    assert result["dynamic_reserve_min_soc_percent"] == 10.0
    assert result["dynamic_reserve_max_soc_percent"] == 10.0
    assert result["next_usable_solar"] is None
    assert result["solar_horizon_complete"] is False
    assert result["solar_horizon_incomplete_slots"] == 288
    assert result["safety_charge_kwh"] == 0.0


def test_alpha63_dynamic_reserve_drops_at_usable_solar() -> None:
    m = _load("automatic_planner_model")
    energy, solar, prices = _axis()
    for index in range(8):
        energy[index]["home_kwh"] = 0.08
    for index in range(8, 16):
        energy[index]["home_kwh"] = 0.02
        solar[index]["solar_kwh"] = 0.02

    result = m.build_automatic_plan(
        energy_slots=energy,
        solar_slots=solar,
        plans=[],
        start_soc_percent=60,
        capacity_kwh=7.1,
        price_by_start=prices,
    )
    assert result["dynamic_reserve_start_soc_percent"] > 10.0
    assert result["native_slots"][8][
        "dynamic_reserve_floor_start_soc_percent"
    ] == 10.0
    assert result["native_slots"][8]["next_usable_solar"].endswith(
        "02:00:00+00:00"
    )


def test_alpha63_safety_does_not_disable_later_arbitrage() -> None:
    m = _load("automatic_planner_model")
    energy, solar, prices = _axis(home=0.0, solar=0.0)

    # A real dynamic reserve shortage before the first usable solar pair.
    for index in range(8):
        energy[index]["home_kwh"] = 0.05
    for index in range(8, 16):
        energy[index]["home_kwh"] = 0.02
        solar[index]["solar_kwh"] = 0.02

    # A later ordinary arbitrage opportunity, deliberately below peak-sale.
    prices[energy[20]["start"]]["import_all_in"] = 0.05
    prices[energy[24]["start"]]["export_all_in"] = 0.45

    result = m.build_automatic_plan(
        energy_slots=energy,
        solar_slots=solar,
        plans=[],
        start_soc_percent=12,
        capacity_kwh=7.1,
        price_by_start=prices,
        peak_sale_threshold_eur_per_kwh=0.80,
    )
    assert result["safety_charge_needed"] is True
    assert result["safety_charge_kwh"] > 0.0
    assert "veiligheidsladen" in result["candidate_types"]
    assert "handelsladen" in result["candidate_types"]
    assert "handel_ontladen" in result["candidate_types"]
    assert result["trade_charge_kwh"] > 0.0
    assert result["trade_discharge_kwh"] > 0.0
    assert result["physical_execution_authority"] is False


def test_alpha63_policy_identity_and_read_only_boundary() -> None:
    runtime = (INTEGRATION / "automatic_planner_runtime.py").read_text(
        encoding="utf-8"
    )
    model = (INTEGRATION / "automatic_planner_model.py").read_text(
        encoding="utf-8"
    )
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")

    assert (
        'PLANNER_POLICY_VERSION = "alpha6_3_dynamic_reserve_parity_v1"'
        in runtime
    )
    assert (
        "first_of_two_consecutive_full_clock_hours_"
        in model
    )
    assert "dynamic_reserve_rule" in model
    assert "dynamic_reserve_max_soc_percent" in sensor
    assert "automatic_plan_store_writes" in model
    assert "physical_execution_authority" in model
    assert "async_call(" not in model
    assert "DOEMSScheduler" not in model
