"""Regressions for one route-wide tolerance budget and AC/DC diagnostics."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys

import pytest


_spec = importlib.util.spec_from_file_location(
    "doems_plan72_tolerance_test",
    Path(__file__).resolve().parents[1] / "custom_components/doems/planner_72h.py",
)
planner = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = planner
_spec.loader.exec_module(planner)

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
TOLERANCE_BATTERY_KWH = 1e-5


def run(home, *, trade_enabled=False, **changes):
    stamps = [NOW + timedelta(minutes=15 * i) for i in range(288)]
    homes = [{"start": stamp, "energy_kwh": home(i) if callable(home) else home}
             for i, stamp in enumerate(stamps)]
    solar = [{"start": stamp, "energy_kwh": 0.0} for stamp in stamps]
    tariffs = [{"start": stamp, "import_all_in": .10 if i % 2 == 0 else .30,
                "export_all_in": .05 if i % 2 == 0 else .80, "kind": "forecast"}
               for i, stamp in enumerate(stamps)]
    options = dict(now=NOW, soc_percent=100, capacity_kwh=7.2,
                   min_soc_percent=5, reserve_percent=5,
                   charge_efficiency=.92, discharge_efficiency=.92,
                   max_charge_power_w=100, max_discharge_power_w=100)
    options.update(changes)
    return planner.calculate_plan72(homes, solar, tariffs,
                                    trade_enabled=trade_enabled, **options)


def raw_requirement(result, charge_efficiency=.92, discharge_efficiency=.92):
    battery_need = (max(row["reserve_gap_kwh"] for row in result["timeline"])
                    + sum(row["uncovered_home_kwh"] for row in result["timeline"])
                    / discharge_efficiency)
    return battery_need / charge_efficiency


def test_seven_trade_fixture_cannot_spend_tolerance_seven_times():
    # Before the fix: baseline ready, seven accepted trades, final reserve gap
    # 5.855383831e-5 stored kWh, limited, despite each step increasing <1e-5.
    baseline = run(.022)
    traded = run(.022, trade_enabled=True)
    assert baseline["reserve_satisfied"]
    assert baseline["remaining_charge_need_kwh"] == 0
    assert traded["trade"]["accepted_count"] > 1
    assert traded["status"] == "ready"
    assert traded["reason"] == "sequential_plan_ready"
    assert traded["reserve_breach_count"] == 0
    for before, after in zip(baseline["timeline"], traded["timeline"]):
        assert after["reserve_gap_kwh"] <= max(before["reserve_gap_kwh"], TOLERANCE_BATTERY_KWH)
        assert after["reserve_min_gap_kwh"] <= max(before["reserve_min_gap_kwh"], TOLERANCE_BATTERY_KWH)
    assert traded["remaining_charge_need_kwh"] == pytest.approx(raw_requirement(traded), abs=1e-12)
    assert traded["remaining_charge_need_kwh"] <= traded["remaining_charge_need_tolerance_kwh"]


def test_two_kw_trade_fixture_has_consistent_status_and_reason():
    # Before the fix: ready with remaining_physical_shortfall.  Its stored gap
    # 9.863946629e-6 was below tolerance, while AC need 1.072168112e-5 was above
    # the same numeric constant because the latter included charging losses.
    result = run(.08, trade_enabled=True,
                 max_charge_power_w=2000, max_discharge_power_w=2000)
    assert result["trade"]["accepted_count"] > 0
    assert result["status"] == "ready"
    assert result["reason"] == "sequential_plan_ready"
    assert result["remaining_charge_need_kwh"] == pytest.approx(raw_requirement(result), abs=1e-12)
    assert result["remaining_charge_need_kwh"] <= result["remaining_charge_need_tolerance_kwh"]


def test_preexisting_small_residue_does_not_receive_a_second_tolerance_budget():
    home = ((7.2 - .72) + .9 * TOLERANCE_BATTERY_KWH) * .92 / 288
    baseline = run(home)
    traded = run(home, trade_enabled=True)
    assert baseline["status"] == "ready"
    baseline_gap = max(row["reserve_gap_kwh"] for row in baseline["timeline"])
    assert .8 * TOLERANCE_BATTERY_KWH < baseline_gap < TOLERANCE_BATTERY_KWH
    assert traded["trade"]["accepted_count"] > 0
    assert traded["reserve_satisfied"]
    assert traded["status"] == "ready"
    assert traded["remaining_charge_need_kwh"] <= traded["remaining_charge_need_tolerance_kwh"]


@pytest.mark.parametrize("charge_efficiency", [.92, .5])
def test_small_raw_ac_requirement_is_preserved_with_its_matching_tolerance(charge_efficiency):
    battery_gap = .99 * TOLERANCE_BATTERY_KWH
    result = run(lambda i: battery_gap * .92 if i == 287 else 0,
                 soc_percent=10, max_charge_power_w=0,
                 charge_efficiency=charge_efficiency)
    assert result["status"] == "ready"
    assert result["reason"] == "sequential_plan_ready"
    assert result["reserve_breach_count"] == 0
    assert result["remaining_charge_need_kwh"] == pytest.approx(battery_gap / charge_efficiency, abs=1e-12)
    assert result["remaining_charge_need_kwh"] > TOLERANCE_BATTERY_KWH
    assert result["remaining_charge_need_tolerance_kwh"] == TOLERANCE_BATTERY_KWH / charge_efficiency
    assert result["remaining_charge_need_kwh"] <= result["remaining_charge_need_tolerance_kwh"]


def test_material_shortfall_stays_limited_even_when_display_would_round_to_zero():
    battery_gap = .001
    result = run(lambda i: battery_gap * .92 if i == 287 else 0,
                 soc_percent=10, max_charge_power_w=0)
    assert result["valid"] and result["status"] == "limited"
    assert result["reason"] == "remaining_physical_shortfall"
    assert result["reserve_breach_count"] == 1
    assert result["remaining_charge_need_kwh"] == pytest.approx(battery_gap / .92)
    assert result["remaining_charge_need_kwh"] > result["remaining_charge_need_tolerance_kwh"]
    assert f"{result['remaining_charge_need_kwh']:.2f}" == "0.00"


def test_uncovered_household_energy_is_classified_as_a_horizon_sum():
    result = run(lambda i: .6 * TOLERANCE_BATTERY_KWH if i in (286, 287) else 0,
                 soc_percent=5, reserve_percent=0, max_charge_power_w=0)
    assert all(row["uncovered_home_kwh"] < TOLERANCE_BATTERY_KWH for row in result["timeline"])
    assert result["reserve_breach_count"] == 0
    assert result["valid"] and result["status"] == "limited"
    assert result["reason"] == "remaining_physical_shortfall"
    assert result["remaining_charge_need_kwh"] == pytest.approx(1.2 * TOLERANCE_BATTERY_KWH / (.92 * .92))
    assert result["remaining_charge_need_kwh"] > result["remaining_charge_need_tolerance_kwh"]
