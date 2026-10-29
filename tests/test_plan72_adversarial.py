"""Independent physical, timing and refusal checks for observational Plan72.

These tests assert measurable contracts rather than a particular ordering of
the planner's economic search.  Nothing in this module calls Home Assistant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import math
from pathlib import Path
import random
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "doems_plan72_adversarial_model", ROOT / "custom_components/doems/planner_72h.py"
)
MODEL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODEL
SPEC.loader.exec_module(MODEL)

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
FLOW_KEYS = (
    "solar_to_home_kwh", "charge_from_solar_kwh",
    "charge_from_grid_safety_kwh", "charge_from_grid_trade_kwh",
    "charge_from_grid_manual_kwh", "discharge_to_home_kwh",
    "discharge_to_grid_kwh", "discharge_to_grid_trade_kwh",
    "discharge_to_grid_manual_kwh", "grid_import_for_home_kwh",
    "solar_export_kwh", "losses_kwh",
)


def inputs(home=0.0, solar=0.0, imp=0.20, exp=0.05):
    stamps = [NOW + timedelta(minutes=15 * i) for i in range(288)]
    return (
        [{"start": t, "energy_kwh": home} for t in stamps],
        [{"start": t, "energy_kwh": solar} for t in stamps],
        [{"start": t, "import_all_in": imp, "export_all_in": exp, "kind": "known"} for t in stamps],
    )


def plan(rows=None, **overrides):
    options = dict(
        now=NOW, soc_percent=50, capacity_kwh=7.2,
        min_soc_percent=5, reserve_percent=5,
        charge_efficiency=0.92, discharge_efficiency=0.92,
        max_charge_power_w=3200, max_discharge_power_w=3200,
        trade_enabled=False,
    )
    options.update(overrides)
    return MODEL.calculate_plan72(*(rows or inputs()), **options)


def manual(action="charge", *, start=NOW, runtime=0.25, power=1000, target=100, **extra):
    return dict(
        id="manual-one", action=action, start_time=start.isoformat(),
        power_w=power, target_soc=target, max_runtime_h=runtime, **extra,
    )


def charge(row):
    return row["charge_from_solar_kwh"] + sum(
        row[f"charge_from_grid_{origin}_kwh"] for origin in ("safety", "trade", "manual")
    )


def discharge(row):
    return row["discharge_to_home_kwh"] + row["discharge_to_grid_kwh"]


def assert_conservation(result, *, capacity=7.2, eta_in=0.92, eta_out=0.92,
                        charge_w=3200, discharge_w=3200):
    assert result["valid"] is True
    assert result["execution_enabled"] is False
    assert len(result["timeline"]) == 288
    previous = capacity * result["start_soc"] / 100
    for index, row in enumerate(result["timeline"]):
        assert datetime.fromisoformat(row["start"]) == NOW + timedelta(minutes=15 * index)
        assert row["stored_start_kwh"] == pytest.approx(previous, abs=1e-8)
        assert row["stored_end_kwh"] == pytest.approx(
            previous + charge(row) * eta_in - discharge(row) / eta_out, abs=1e-8
        )
        assert 0 <= row["stored_end_kwh"] <= capacity + 1e-8
        assert row["home_kwh"] == pytest.approx(
            row["solar_to_home_kwh"] + row["discharge_to_home_kwh"] + row["grid_import_for_home_kwh"], abs=1e-8
        )
        assert row["solar_kwh"] == pytest.approx(
            row["solar_to_home_kwh"] + row["charge_from_solar_kwh"] + row["solar_export_kwh"], abs=1e-8
        )
        assert row["discharge_to_grid_kwh"] == pytest.approx(
            row["discharge_to_grid_trade_kwh"] + row["discharge_to_grid_manual_kwh"], abs=1e-8
        )
        assert row["losses_kwh"] == pytest.approx(
            charge(row) * (1 - eta_in) + discharge(row) * (1 / eta_out - 1), abs=1e-8
        )
        grid_in = row["grid_import_for_home_kwh"] + sum(
            row[f"charge_from_grid_{origin}_kwh"] for origin in ("safety", "trade", "manual")
        )
        grid_out = row["solar_export_kwh"] + row["discharge_to_grid_kwh"]
        assert grid_in + row["solar_kwh"] - grid_out - row["home_kwh"] - row["losses_kwh"] == pytest.approx(
            row["stored_end_kwh"] - row["stored_start_kwh"], abs=1e-8
        )
        assert row["segments"]
        cursor = datetime.fromisoformat(row["start"])
        segment_energy = row["stored_start_kwh"]
        for segment in row["segments"]:
            assert datetime.fromisoformat(segment["start"]) == cursor
            end = datetime.fromisoformat(segment["end"])
            dt = (end - cursor).total_seconds() / 3600
            assert dt == pytest.approx(segment["duration_hours"], abs=1e-9)
            assert dt > 0
            assert segment["stored_start_kwh"] == pytest.approx(segment_energy, abs=1e-8)
            assert charge(segment) <= charge_w / 1000 * dt + 1e-8
            assert discharge(segment) <= discharge_w / 1000 * dt + 1e-8
            assert min(charge(segment), discharge(segment)) == pytest.approx(0, abs=1e-8)
            for key in FLOW_KEYS:
                assert math.isfinite(segment[key]) and segment[key] >= -1e-8
            segment_energy = segment["stored_end_kwh"]
            cursor = end
        assert cursor == datetime.fromisoformat(row["end"])
        assert segment_energy == pytest.approx(row["stored_end_kwh"], abs=1e-8)
        for key in FLOW_KEYS:
            assert row[key] == pytest.approx(sum(segment[key] for segment in row["segments"]), abs=1e-8)
        previous = row["stored_end_kwh"]
    for key in FLOW_KEYS:
        assert result["totals"][key] == pytest.approx(sum(row[key] for row in result["timeline"]), abs=1e-8)


def test_randomized_partial_manual_route_conserves_all_energy_and_shared_power():
    home, solar, prices = inputs()
    rng = random.Random(72615)
    for i in range(20):
        home[i]["energy_kwh"] = rng.uniform(0.03, 0.25)
        solar[i]["energy_kwh"] = rng.uniform(0.01, 0.32)
        prices[i]["import_all_in"] = rng.uniform(0.12, 0.4)
    supplied = [
        manual(start=NOW + timedelta(minutes=5), runtime=0.35, power=4000, target=95),
        {**manual("discharge", start=NOW + timedelta(hours=1, minutes=7), runtime=0.4, power=2800, target=20), "id": "manual-two"},
        {**manual(start=NOW + timedelta(hours=2, minutes=11), runtime=0.18, power=800, target=90), "id": "manual-three"},
    ]
    result = plan((home, solar, prices), capacity_kwh=4.8, min_soc_percent=10,
                  charge_efficiency=0.87, discharge_efficiency=0.93,
                  max_charge_power_w=2300, max_discharge_power_w=1700,
                  manual_plans=supplied)
    assert_conservation(result, capacity=4.8, eta_in=0.87, eta_out=0.93, charge_w=2300, discharge_w=1700)


def test_manual_partial_quarters_count_only_exact_twenty_minutes():
    supplied = [manual(start=NOW + timedelta(minutes=5), runtime=1 / 3, power=1200)]
    result = plan(manual_plans=supplied)
    assert result["totals"]["charge_from_grid_manual_kwh"] == pytest.approx(0.4)
    progress = result["manual"]["plans"][0]
    assert progress["duration_hours"] == pytest.approx(1 / 3)
    assert result["end_soc"] == pytest.approx((3.6 + 0.4 * 0.92) / 7.2 * 100)
    assert_conservation(result)


def test_active_manual_continuation_never_credits_elapsed_energy():
    supplied = [manual(start=NOW - timedelta(minutes=10), runtime=0.5, lifecycle_status="active")]
    result = plan(manual_plans=supplied)
    assert result["totals"]["charge_from_grid_manual_kwh"] == pytest.approx(1 / 3)
    assert result["manual"]["plans"][0]["duration_hours"] == pytest.approx(1 / 3)
    assert_conservation(result)


def test_satisfied_manual_target_never_restarts_after_passive_soc_drift():
    home, solar, prices = inputs()
    for row in home[:4]:
        row["energy_kwh"] = 0.05
    result = plan((home, solar, prices), soc_percent=60,
                  manual_plans=[manual(runtime=1.0, target=50)])
    assert result["totals"]["charge_from_grid_manual_kwh"] == 0
    assert result["manual"]["plans"][0]["target_reached"] is True
    assert result["manual"]["plans"][0]["duration_hours"] == 0
    assert result["end_soc"] < 60
    assert_conservation(result)


def test_manual_runtime_unmet_target_is_visible_as_limited_valid_plan():
    result = plan(manual_plans=[manual(runtime=0.25, power=1000, target=100)])
    assert result["valid"] is True
    assert result["status"] == "limited"
    progress = result["manual"]["plans"][0]
    assert progress["target_reached"] is False
    assert progress["limited"] is True
    assert progress["reasons"]
    assert result["totals"]["charge_from_grid_manual_kwh"] == pytest.approx(0.25)


def test_manual_negative_export_preserves_household_supply_but_blocks_export():
    home, solar, prices = inputs(exp=-0.05)
    home[0]["energy_kwh"] = 0.10
    result = plan((home, solar, prices), manual_plans=[manual("discharge", target=5)])
    assert result["valid"] is True
    assert result["totals"]["discharge_to_grid_manual_kwh"] == 0
    assert result["timeline"][0]["discharge_to_home_kwh"] == pytest.approx(0.1)
    assert result["manual"]["plans"][0]["limited"] is True
    assert result["manual"]["plans"][0]["reasons"]
    assert_conservation(result)


def test_negative_export_block_keeps_its_reason_when_no_household_load_exists():
    result = plan(inputs(exp=-0.05), manual_plans=[manual("discharge", target=5)])
    assert result["totals"]["discharge_to_grid_manual_kwh"] == 0
    assert "negative_export_price" in result["manual"]["plans"][0]["reasons"]


def test_automatic_export_is_absent_when_all_export_prices_are_negative():
    result = plan(inputs(exp=-0.10), soc_percent=100, trade_enabled=True)
    assert result["valid"] is True
    assert result["totals"]["discharge_to_grid_trade_kwh"] == 0
    assert result["totals"]["charge_from_grid_trade_kwh"] == 0


def test_trade_cannot_make_a_previously_reachable_manual_target_unreachable():
    home, solar, prices = inputs(exp=-0.05)
    prices[2]["export_all_in"] = 0.60
    supplied = [manual(start=NOW + timedelta(hours=1), runtime=0.25, power=1000, target=80)]
    baseline = plan((home, solar, prices), soc_percent=80, manual_plans=supplied)
    traded = plan((home, solar, prices), soc_percent=80, manual_plans=supplied, trade_enabled=True)
    assert baseline["manual"]["plans"][0]["target_reached"] is True
    assert traded["manual"]["plans"][0]["target_reached"] is True
    assert traded["manual"]["plans"][0]["remaining_target_kwh"] <= 1e-5
    assert_conservation(traded)


def test_profitable_grid_cycle_is_considered_even_with_no_initial_tradable_energy():
    # A valid small buy followed by a sale is possible throughout this route.
    # Unfunded direct-sale candidates must not hide every funded trade candidate.
    rows = inputs(imp=0.20, exp=0.60)
    baseline = plan(rows, soc_percent=10)
    traded = plan(rows, soc_percent=10, trade_enabled=True)
    exported = traded["totals"]["discharge_to_grid_trade_kwh"]
    assert exported > 0
    assert traded["totals"]["charge_from_grid_trade_kwh"] > 0
    saving = sum(row["cost"] for row in baseline["timeline"]) - sum(row["cost"] for row in traded["timeline"])
    assert saving >= 0.10 * exported - 1e-8
    assert traded["reserve_satisfied"] is True
    assert_conservation(traded)


def test_trade_margin_is_checked_per_delivered_ac_kwh_after_losses():
    home, solar, prices = inputs(imp=0.20, exp=-0.05)
    prices[3]["export_all_in"] = 0.32
    # Nominal spread 0.12 exceeds 0.10, but 0.32 - 0.20/(0.92*0.92)
    # is only about 0.0837 per AC kWh delivered after both conversion losses.
    result = plan((home, solar, prices), soc_percent=10, trade_enabled=True)
    assert result["totals"]["charge_from_grid_trade_kwh"] == 0
    assert result["totals"]["discharge_to_grid_trade_kwh"] == 0


def test_best_trade_diagnostics_do_not_report_the_last_worse_accepted_sale():
    home, solar, prices = inputs(imp=10.0, exp=-0.05)
    for index, price in enumerate((0.80, 0.50, 0.30)):
        prices[index]["export_all_in"] = price
    result = plan((home, solar, prices), soc_percent=100, trade_enabled=True)
    assert result["trade"]["accepted_count"] >= 2
    assert result["trade"]["best_discharge_price"] == pytest.approx(0.80)
    assert result["trade"]["best_discharge_time"] == NOW.isoformat()


def test_direct_trade_export_cannot_consume_energy_reserved_for_future_home():
    home, solar, prices = inputs(imp=2.0, exp=-0.05)
    prices[2]["export_all_in"] = 0.60
    home[8]["energy_kwh"] = 0.20
    baseline = plan((home, solar, prices), soc_percent=15)
    traded = plan((home, solar, prices), soc_percent=15, trade_enabled=True)
    # Initial stored energy 1.08; target reserve .72; future home requires
    # .20/.92 stored kWh. At most the remainder can be exported deliberately.
    export_bound = (1.08 - 0.72 - 0.20 / 0.92) * 0.92
    assert traded["totals"]["discharge_to_grid_trade_kwh"] <= export_bound + 1e-4
    assert traded["timeline"][8]["discharge_to_home_kwh"] >= baseline["timeline"][8]["discharge_to_home_kwh"] - 1e-5
    assert traded["timeline"][8]["grid_import_for_home_kwh"] <= baseline["timeline"][8]["grid_import_for_home_kwh"] + 1e-5
    assert_conservation(traded)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), True])
def test_invalid_export_prices_block_whole_plan_without_fictitious_zero_totals(bad):
    home, solar, prices = inputs()
    prices[31]["export_all_in"] = bad
    result = plan((home, solar, prices))
    assert result["valid"] is False
    assert result["execution_enabled"] is False
    assert result["timeline"] == []
    assert result["totals"]
    assert all(value is None for value in result["totals"].values())


def test_manual_conflict_rejects_entire_plan_with_no_imaginary_charge():
    first = manual(runtime=1.0)
    second = {**manual("discharge", start=NOW + timedelta(minutes=30), target=5), "id": "second"}
    result = plan(manual_plans=[first, second])
    assert result["valid"] is False
    assert result["manual"]["conflicts_count"] == 1
    assert result["timeline"] == []
    assert all(value is None for value in result["totals"].values())


def test_shared_pv_and_manual_charge_respect_total_battery_power():
    home, solar, prices = inputs()
    home[0]["energy_kwh"] = 0.1
    solar[0]["energy_kwh"] = 0.6
    result = plan((home, solar, prices), manual_plans=[manual(power=3200)])
    first = result["timeline"][0]
    assert first["solar_to_home_kwh"] == pytest.approx(0.1)
    assert first["charge_from_solar_kwh"] == pytest.approx(0.5)
    assert first["charge_from_grid_manual_kwh"] == pytest.approx(0.3)
    assert charge(first) == pytest.approx(0.8)
    assert_conservation(result)


def test_almost_full_battery_caps_manual_charge_at_real_headroom():
    result = plan(soc_percent=99, manual_plans=[manual(power=3200)])
    assert result["totals"]["charge_from_grid_manual_kwh"] == pytest.approx(0.072 / 0.92)
    assert result["end_soc"] == pytest.approx(100)
    assert result["manual"]["plans"][0]["target_reached"] is True
    assert_conservation(result)


def test_manual_grid_export_cannot_cross_the_configured_reserve():
    result = plan(soc_percent=15, manual_plans=[manual("discharge", power=3200, target=5)])
    assert result["valid"] is True
    assert result["status"] == "limited"
    assert result["totals"]["discharge_to_grid_manual_kwh"] == pytest.approx((1.08 - 0.72) * 0.92)
    assert result["min_soc"] == pytest.approx(10)
    assert "reserve_limited" in result["manual"]["plans"][0]["reasons"]
    assert_conservation(result)


def test_passive_household_supply_does_not_invent_a_software_reserve_hold():
    home, solar, prices = inputs()
    home[0]["energy_kwh"] = 0.4
    result = plan((home, solar, prices), soc_percent=15, max_charge_power_w=0)
    assert result["valid"] is True
    assert result["status"] == "limited"
    assert result["totals"]["discharge_to_home_kwh"] == pytest.approx(0.4)
    assert result["totals"]["grid_import_for_home_kwh"] == 0
    assert 5 < result["min_soc"] < 10
    assert result["min_soc"] == pytest.approx((1.08 - 0.4 / 0.92) / 7.2 * 100)
    assert result["reserve_satisfied"] is False
    assert_conservation(result, charge_w=0)


def test_zero_charge_limit_produces_visible_shortfall_without_futile_search(monkeypatch):
    # Count replays instead of asserting a machine-dependent wall-clock time.
    # A known zero charge limit cannot improve the passive route at any price.
    original = MODEL._Model.simulate
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        assert calls <= 300, "zero charging authority must not search thousands of impossible routes"
        return original(*args, **kwargs)

    monkeypatch.setattr(MODEL._Model, "simulate", counted)
    result = plan(inputs(home=0.1), soc_percent=5, max_charge_power_w=0)
    assert result["valid"] is True
    assert result["status"] == "limited"
    assert result["reserve_satisfied"] is False
    assert result["remaining_charge_need_kwh"] > 0
    assert result["totals"]["charge_from_grid_safety_kwh"] == 0
    assert_conservation(result, charge_w=0)
