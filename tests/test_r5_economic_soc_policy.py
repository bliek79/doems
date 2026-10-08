from __future__ import annotations

from test_alpha7_1_planner_migration_contract import _axis, _prices, _load


def _run(energy, solar, prices, *, soc=25.0):
    model = _load("automatic_combined_planner_model")
    return model.build_planner_bundle(
        energy_slots=energy, solar_slots=solar, plans=[],
        start_soc_percent=soc, capacity_kwh=7.1,
        price_by_start=prices,
    )["automatic"]


def test_r5_future_home_need_never_becomes_hard_soc_floor():
    energy, solar = _axis(home_kwh=0.11)
    for i in range(100, 108):
        solar[i]["solar_kwh"] = 0.25
    result = _run(energy, solar, _prices(energy, import_price=0.30), soc=55)
    assert result["native_slot_count"] == 288
    assert result["dynamic_reserve_max_soc_percent"] == 10.0
    assert result["hard_safety_floor_soc"] == 10.0
    assert max(row["dynamic_reserve_floor_end_soc_percent"] for row in result["native_slots"]) == 10.0
    assert min(row["end_soc_percent"] for row in result["native_slots"]) >= 10.0
    assert result["planning_need_until_solar_kwh"] > 0


def test_r5_cheaper_grid_charge_before_usable_solar_avoids_expensive_home_import():
    energy, solar = _axis(home_kwh=0.20)
    for i in range(8):
        energy[i]["home_kwh"] = 0.0
    for i in range(32, 40):
        solar[i]["solar_kwh"] = 0.50
    prices = _prices(energy, import_price=0.42, export_price=0.10)
    for i in range(8):
        prices[energy[i]["start"]]["import_all_in"] = 0.09
    result = _run(energy, solar, prices, soc=10.0)
    assert result["native_slot_count"] == 288
    assert sum(row["charge_from_grid_kwh"] for row in result["native_slots"][:8]) > 0
    assert result["unavoidable_grid_import_kwh"] >= 0
    assert result["dynamic_reserve_max_soc_percent"] == 10.0
    assert result["physical_execution_enabled"] is False


def test_r5_equal_price_does_not_buy_economic_precharge():
    energy, solar = _axis(home_kwh=0.04)
    result = _run(energy, solar, _prices(energy, import_price=0.20), soc=12)
    assert result["economic_reserved_kwh"] == 0
