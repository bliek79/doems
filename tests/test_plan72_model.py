"""Physical and economic contracts for the observational Plan72 engine."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

_spec = importlib.util.spec_from_file_location(
    "doems_plan72_model_test", Path(__file__).resolve().parents[1] / "custom_components/doems/planner_72h.py"
)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
calculate_plan72 = _module.calculate_plan72
NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


def rows(value, *, start=NOW):
    return [{"start": start + timedelta(minutes=15 * i),
             "energy_kwh": value(i) if callable(value) else value} for i in range(288)]


def prices(import_price=0.30, export_price=0.05, *, start=NOW):
    return [{"start": start + timedelta(minutes=15 * i),
             "import_all_in": import_price(i) if callable(import_price) else import_price,
             "export_all_in": export_price(i) if callable(export_price) else export_price,
             "kind": "forecast"} for i in range(288)]


def run(home=0.0, solar=0.0, tariff=None, **changes):
    arguments = dict(now=NOW, soc_percent=50, capacity_kwh=7.2, min_soc_percent=5,
                     reserve_percent=5, max_charge_power_w=3200, max_discharge_power_w=3200,
                     trade_enabled=False)
    arguments.update(changes)
    return calculate_plan72(rows(home), rows(solar), tariff or prices(), **arguments)


def assert_conserved(plan, capacity=7.2, charge_eff=0.92, discharge_eff=0.92, power=3200):
    previous = plan["start_soc"] * capacity / 100
    for row in plan["timeline"]:
        charge_grid = sum(row[f"charge_from_grid_{source}_kwh"] for source in ("safety", "trade", "manual"))
        charge = charge_grid + row["charge_from_solar_kwh"]
        discharge = row["discharge_to_home_kwh"] + row["discharge_to_grid_kwh"]
        exported = row["solar_export_kwh"] + row["discharge_to_grid_kwh"]
        imported = row["grid_import_for_home_kwh"] + charge_grid
        assert row["solar_kwh"] + imported + discharge == pytest.approx(row["home_kwh"] + charge + exported, abs=1e-9)
        assert row["stored_start_kwh"] == pytest.approx(previous, abs=1e-9)
        assert row["stored_end_kwh"] == pytest.approx(previous + charge * charge_eff - discharge / discharge_eff, abs=1e-9)
        assert charge <= power / 1000 * 0.25 + 1e-9
        assert discharge <= power / 1000 * 0.25 + 1e-9
        assert sum(segment["duration_hours"] for segment in row["segments"]) == pytest.approx(.25, abs=1e-9)
        for segment in row["segments"]:
            grid_in = sum(segment[f"charge_from_grid_{source}_kwh"] for source in ("safety", "trade", "manual"))
            input_kwh = segment["charge_from_solar_kwh"] + grid_in
            output_kwh = segment["discharge_to_home_kwh"] + segment["discharge_to_grid_kwh"]
            assert not (input_kwh > 1e-9 and output_kwh > 1e-9)
            assert abs(segment["battery_power_w"]) <= power + 1e-6
            assert 0 <= segment["stored_end_kwh"] <= capacity + 1e-9
        previous = row["stored_end_kwh"]


def test_exact_horizon_and_no_physical_side_effect_contract():
    result = run()
    assert result["valid"] and result["status"] == "ready"
    assert result["horizon_hours"] == 72 and result["slot_count"] == 288
    assert result["end"] == (NOW + timedelta(hours=72)).isoformat()
    assert result["observational_only"] and result["execution_enabled"] is False
    assert result["start_soc"] == result["end_soc"] == 50
    assert_conserved(result)


def test_no_solar_need_larger_than_capacity_is_spread_across_safe_windows():
    result = run(home=.15, tariff=prices(lambda i: .10 if i % 96 >= 50 else .30))
    assert result["valid"] and result["reserve_satisfied"]
    assert result["totals"]["charge_from_grid_safety_kwh"] > 7.2
    assert result["min_soc"] >= 10 - .001
    assert_conserved(result)


def test_cheapest_window_after_deadline_cannot_supply_past_demand():
    result = run(home=lambda i: .3 if i < 8 else 0,
                 tariff=prices(lambda i: .01 if i == 12 else .20 if i == 1 else .40),
                 soc_percent=20)
    assert result["timeline"][1]["charge_from_grid_safety_kwh"] > 0
    assert result["timeline"][12]["charge_from_grid_safety_kwh"] == 0
    assert result["reserve_satisfied"]


def test_later_cheaper_window_wins_when_battery_can_reach_it():
    result = run(home=lambda i: .1 if i < 64 else 0,
                 tariff=prices(lambda i: .10 if 20 <= i < 26 else .20 if i == 4 else .40),
                 soc_percent=60)
    assert sum(row["charge_from_grid_safety_kwh"] for row in result["timeline"][20:26]) > 0
    assert result["timeline"][4]["charge_from_grid_safety_kwh"] == 0


def test_pv_has_priority_and_does_not_invent_grid_energy():
    result = run(home=.02, solar=lambda i: .6 if 12 <= i % 96 < 20 else 0, soc_percent=70)
    assert result["totals"]["solar_to_home_kwh"] > 0
    assert result["totals"]["charge_from_solar_kwh"] > 0
    assert result["totals"]["charge_from_grid_safety_kwh"] == 0
    assert result["totals"]["solar_export_kwh"] > 0
    assert_conserved(result)


def test_zero_charge_power_returns_honest_limited_route():
    result = run(home=.1, soc_percent=5, max_charge_power_w=0)
    assert result["valid"] and result["status"] == "limited"
    assert not result["reserve_satisfied"]
    assert result["remaining_charge_need_kwh"] > 7.2
    assert result["projection_count"] <= 3
    assert result["totals"]["charge_from_grid_safety_kwh"] == 0
    assert result["totals"]["grid_import_for_home_kwh"] == pytest.approx(28.8)


def test_measured_soc_below_hardware_floor_is_never_raised_by_clamping():
    result = run(soc_percent=2, max_charge_power_w=0)
    assert result["timeline"][0]["soc_start"] == 2
    assert result["end_soc"] == pytest.approx(2)
    assert result["status"] == "limited"


def test_initial_reserve_breach_stays_visible_after_first_quarter_recovers():
    result = run(soc_percent=5)
    assert result["valid"] and result["status"] == "limited"
    assert result["reason"] == "reserve_breach_in_projection"
    assert not result["reserve_satisfied"] and result["reserve_breach_count"] == 1
    assert result["deadline_reserve_satisfied"] and result["reserve_end_breach_count"] == 0
    assert result["remaining_charge_need_kwh"] == 0
    assert result["timeline"][0]["min_soc"] == 5


@pytest.mark.parametrize("change", [
    {"soc_percent": None}, {"capacity_kwh": 0}, {"capacity_kwh": float("nan")},
    {"max_charge_power_w": float("inf")}, {"reserve_percent": 99},
    {"charge_efficiency": 0}, {"discharge_efficiency": 1.1}, {"soc_percent": True},
])
def test_invalid_battery_inputs_have_no_fabricated_numeric_totals(change):
    result = run(**change)
    assert not result["valid"] and result["timeline"] == []
    assert all(value is None for value in result["totals"].values())


@pytest.mark.parametrize("fault", ["missing", "duplicate", "nan", "negative", "naive"])
def test_invalid_forecast_contract_fails_closed(fault):
    home, solar, tariff = rows(.1), rows(0), prices()
    if fault == "missing":
        home.pop(12)
    elif fault == "duplicate":
        solar.append(dict(solar[6]))
    elif fault == "nan":
        home[8]["energy_kwh"] = float("nan")
    elif fault == "negative":
        solar[2]["energy_kwh"] = -.01
    else:
        home[3]["start"] = home[3]["start"].replace(tzinfo=None)
    result = calculate_plan72(home, solar, tariff, now=NOW, soc_percent=50, capacity_kwh=7.2,
                              min_soc_percent=5, reserve_percent=5, max_charge_power_w=3200,
                              max_discharge_power_w=3200)
    assert not result["valid"] and result["timeline"] == []


def test_negative_prices_are_valid_but_automatic_negative_export_is_blocked():
    result = run(tariff=prices(-.20, -.10), soc_percent=100, trade_enabled=True)
    assert result["valid"]
    assert result["totals"]["discharge_to_grid_trade_kwh"] == 0
    assert result["totals"]["charge_from_grid_trade_kwh"] == 0


def test_safe_profitable_pair_uses_real_export_and_full_losses():
    result = run(tariff=prices(lambda i: .01 if i == 0 else .40,
                              lambda i: .70 if i == 20 else 0),
                 soc_percent=10, trade_enabled=True)
    assert result["valid"] and result["trade"]["profitable"]
    assert result["totals"]["charge_from_grid_trade_kwh"] > 0
    assert result["totals"]["discharge_to_grid_trade_kwh"] > 0
    assert result["trade"]["expected_margin"] >= .10
    assert result["reserve_satisfied"]
    assert_conserved(result)


def test_future_household_energy_cannot_be_sold_at_earlier_high_price():
    result = run(home=lambda i: .2 if i < 30 else 0, soc_percent=100,
                 tariff=prices(.30, lambda i: 1.0 if i == 0 else 0), trade_enabled=True)
    assert result["timeline"][0]["discharge_to_grid_trade_kwh"] < .001
    assert result["reserve_satisfied"]


def test_best_trade_fields_describe_best_accepted_actual_margin():
    result = run(tariff=prices(10, lambda i: (.8, .5, .3)[i] if i < 3 else -.05),
                 soc_percent=100, trade_enabled=True)
    assert result["trade"]["accepted_count"] == 3
    assert result["trade"]["best_discharge_price"] == .8
    assert result["trade"]["best_discharge_time"] == NOW.isoformat()
    assert result["trade"]["expected_margin"] == pytest.approx(.8)
    assert result["trade"]["total_horizon_cost_saving"] == pytest.approx(1.28)
    assert result["trade"]["aggregate_expected_margin"] == pytest.approx(1.6 / 3)


def test_automatic_trade_purchase_cannot_displace_protected_pv_storage():
    # A negative buy price must not silently introduce an exception to PV
    # priority.  The upcoming PV already fills the battery before the sale.
    arguments = dict(solar=lambda i: .8 if 4 <= i < 13 else 0, soc_percent=10,
                     tariff=prices(lambda i: -.5 if i == 0 else .4,
                                   lambda i: .7 if i == 15 else 0))
    baseline = run(**arguments)
    traded = run(**arguments, trade_enabled=True)
    assert traded["valid"]
    assert traded["totals"]["discharge_to_grid_trade_kwh"] > 0
    for before, after in zip(baseline["timeline"], traded["timeline"]):
        assert after["charge_from_solar_kwh"] >= before["charge_from_solar_kwh"] - 1.01e-5
    assert_conserved(traded)


def test_utc_quarters_stay_unique_across_autumn_clock_change():
    now = datetime(2026, 10, 25, 1, 57, tzinfo=ZoneInfo("Europe/Amsterdam"))
    utc = now.astimezone(timezone.utc)
    start = utc.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    result = calculate_plan72(rows(0, start=start), rows(0, start=start), prices(start=start),
                              now=now, soc_percent=50, capacity_kwh=7.2, min_soc_percent=5,
                              reserve_percent=5, max_charge_power_w=3200, max_discharge_power_w=3200,
                              trade_enabled=False)
    assert result["valid"] and len({row["start"] for row in result["timeline"]}) == 288
    assert result["start"] == start.isoformat()
    assert datetime.fromisoformat(result["end"]) - start == timedelta(hours=72)
