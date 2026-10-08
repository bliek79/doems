"""R5 policy parity gate: technical floor, cheapest precharge and manual separation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from test_alpha7_1_planner_migration_contract import _axis, _load, _plan, _prices


def _run(energy, solar, price_by_start, *, soc=25.0, plans=(), margin=0.10):
    model = _load("automatic_combined_planner_model")
    return model.build_planner_bundle(
        energy_slots=energy,
        solar_slots=solar,
        plans=list(plans),
        start_soc_percent=soc,
        capacity_kwh=7.1,
        price_by_start=price_by_start,
        minimum_trade_margin_eur_per_kwh=margin,
    )


def test_r5_unplanned_home_self_consumption_uses_technical_5_not_reserve_10():
    model = _load("automatic_combined_planner_model")
    energy, solar = _axis(home_kwh=0.12)
    axis, blockers = model._validate_time_axis(energy, solar)
    assert blockers == []
    rows = model._simulate(
        axis=[{**row, "prices": {}} for row in axis],
        commitments=[],
        start_soc_percent=10,
        capacity_kwh=7.1,
        charge_efficiency=0.92,
        discharge_efficiency=0.92,
        max_charge_power_w=3500,
        max_discharge_power_w=3500,
        reserve_floor_end_soc=[10.0] * 288,
    )
    assert rows[0]["end_soc_percent"] < 10
    assert rows[0]["discharge_to_home_kwh"] > 0
    assert rows[0]["home_discharge_floor_soc_percent"] == 5
    assert rows[0]["automatic_floor_soc_percent"] == 10
    assert rows[2]["end_soc_percent"] == 5
    assert rows[3]["grid_to_home_kwh"] > 0
    assert all(float(row["end_soc_percent"]) >= 5 for row in rows)


def test_r5_safety_reserve_precharges_in_cheapest_reachable_later_window():
    energy, solar = _axis(home_kwh=0)
    for index in range(16, 40):
        energy[index]["home_kwh"] = 0.15
    prices = _prices(energy, import_price=0.29, export_price=0.05)
    for index in range(8, 16):
        prices[energy[index]["start"]]["import_all_in"] = 0.18
    result = _run(energy, solar, prices, soc=25)
    planner = result["automatic"]
    rows = planner["native_slots"]
    assert result["valid"]
    assert len(rows) == 288
    assert planner["planner_floor_soc_percent"] == 10
    assert planner["dynamic_reserve_max_soc_percent"] == 10
    assert sum(row["charge_from_grid_safety_kwh"] for row in rows[8:16]) > 0.5
    assert sum(row["charge_from_grid_safety_kwh"] for row in rows[0:8]) == 0
    assert all(float(row["end_soc_percent"]) >= 10 - 0.005 for row in rows)
    assert planner["safety_charge_needed"] is True
    assert planner["physical_execution_enabled"] is False


def test_r5_reserve_precharge_not_blocked_by_configured_export_trade_margin():
    energy, solar = _axis(home_kwh=0)
    for index in range(16, 40):
        energy[index]["home_kwh"] = 0.15
    prices = _prices(energy, import_price=0.29, export_price=0.05)
    for index in range(8, 16):
        prices[energy[index]["start"]]["import_all_in"] = 0.18
    result = _run(energy, solar, prices, soc=25, margin=0.30)
    planner = result["automatic"]
    assert sum(float(row["charge_from_grid_safety_kwh"]) for row in planner["native_slots"][8:16]) > 0
    assert planner["minimum_trade_margin_eur_per_kwh"] == 0.30
    assert planner["physical_execution_enabled"] is False


def test_r5_usable_solar_does_not_cutoff_72h_economic_window():
    energy, solar = _axis(home_kwh=0.02)
    for index in range(32, 40):
        solar[index]["solar_kwh"] = 0.25
    for index in range(120, 145):
        energy[index]["home_kwh"] = 0.26
    prices = _prices(energy, import_price=0.28, export_price=0.02)
    for index in range(100, 112):
        prices[energy[index]["start"]]["import_all_in"] = 0.16
    result = _run(energy, solar, prices, soc=30)
    planner = result["automatic"]
    assert planner["native_slot_count"] == 288
    assert planner["next_usable_solar"] is not None
    assert any(
        float(row["charge_from_grid_kwh"]) > 0
        for row in planner["native_slots"][100:112]
    )
    assert planner["dynamic_reserve_max_soc_percent"] == 10


def test_r5_automatic_independent_of_three_manual_slots_combined_owns_priority():
    energy, solar = _axis(home_kwh=0.025)
    prices = _prices(energy)
    t = datetime(2026, 10, 7, tzinfo=timezone.utc)
    manual = [
        _plan(action="laden", start=t + timedelta(hours=3), target_soc=60,
              power_w=700, runtime_h=2, slot=1),
        _plan(action="ontladen", start=t + timedelta(hours=8), target_soc=25,
              power_w=700, runtime_h=2, slot=2),
        _plan(action="laden", start=t + timedelta(hours=13), target_soc=50,
              power_w=700, runtime_h=2, slot=3),
    ]
    with_manual = _run(energy, solar, prices, soc=45, plans=manual)
    without_manual = _run(energy, solar, prices, soc=45)
    assert with_manual["automatic"]["native_slots"] == without_manual["automatic"]["native_slots"]
    assert with_manual["combined"]["manual_commitment_slots"] == [1, 2, 3]
    assert without_manual["combined"]["native_slots"] == without_manual["automatic"]["native_slots"]
    for index, slot in ((12, 1), (32, 2), (52, 3)):
        assert with_manual["combined"]["native_slots"][index]["manual_slots"] == [slot]
        assert with_manual["automatic"]["native_slots"][index]["manual_slots"] == []
    assert not with_manual["physical_execution_enabled"]
