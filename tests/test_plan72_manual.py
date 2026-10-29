"""Manual intents share the same segmented energy route and constraints."""

from datetime import timedelta

import pytest

from test_plan72_model import NOW, assert_conserved, prices, run


def plan(**changes):
    result = dict(id="manual-1", action="charge", start_time=NOW,
                  power_w=1000, target_soc=100, max_runtime_h=.25)
    result.update(changes)
    return result


def test_manual_charge_splits_partial_quarters_without_double_counting():
    item = plan(start_time=NOW + timedelta(minutes=7, seconds=30), max_runtime_h=.25)
    result = run(manual_plans=(item,))
    assert result["valid"]
    assert result["timeline"][0]["charge_from_grid_manual_kwh"] == pytest.approx(.125)
    assert result["timeline"][1]["charge_from_grid_manual_kwh"] == pytest.approx(.125)
    assert result["totals"]["charge_from_grid_manual_kwh"] == pytest.approx(.25)
    assert result["end_soc"] == pytest.approx((3.6 + .25 * .92) / 7.2 * 100)
    assert result["manual"]["plans"][0]["remaining_target_kwh"] > 0
    assert result["status"] == "limited"
    assert_conserved(result)


def test_manual_charge_power_includes_pv_and_supplies_house_from_grid():
    result = run(home=.1, solar=lambda i: .3 if i == 0 else .1,
                 manual_plans=(plan(),))
    first = result["timeline"][0]
    assert first["charge_from_solar_kwh"] == pytest.approx(.2)
    assert first["charge_from_grid_manual_kwh"] == pytest.approx(.05)
    assert first["discharge_to_home_kwh"] == 0
    assert first["solar_to_home_kwh"] == pytest.approx(.1)
    assert_conserved(result)


def test_manual_target_reached_early_stays_complete_after_passive_soc_drops():
    # From 50% to 51% requires 0.0782609 AC kWh.  Later household consumption
    # lowers SOC again; this must not restart the same two-hour manual action.
    result = run(home=lambda i: .05 if i < 8 else 0,
                 manual_plans=(plan(target_soc=51, max_runtime_h=2),))
    assert result["totals"]["charge_from_grid_manual_kwh"] == pytest.approx(.072 / .92)
    assert result["manual"]["plans"][0]["target_reached"]
    assert all(row["charge_from_grid_manual_kwh"] == 0 for row in result["timeline"][1:])
    assert_conserved(result)


def test_already_met_manual_target_does_not_restart_after_passive_discharge():
    result = run(home=lambda i: .1 if i < 4 else 0,
                 manual_plans=(plan(target_soc=40, max_runtime_h=1),))
    assert result["totals"]["charge_from_grid_manual_kwh"] == 0
    assert result["manual"]["plans"][0]["target_reached"]


def test_manual_discharge_serves_home_first_and_respects_shared_limit():
    result = run(home=lambda i: .1 if i == 0 else 0, soc_percent=80,
                 manual_plans=(plan(action="discharge", power_w=1000, target_soc=20),))
    first = result["timeline"][0]
    assert first["discharge_to_home_kwh"] == pytest.approx(.1)
    assert first["discharge_to_grid_manual_kwh"] == pytest.approx(.15)
    assert first["charge_from_grid_safety_kwh"] == 0
    assert_conserved(result)


def test_negative_export_price_limits_manual_discharge_to_household():
    result = run(home=lambda i: .1 if i == 0 else 0, tariff=prices(.3, -.1), soc_percent=80,
                 manual_plans=(plan(action="discharge", power_w=1000, target_soc=20),))
    assert result["totals"]["discharge_to_grid_manual_kwh"] == 0
    assert result["timeline"][0]["discharge_to_home_kwh"] == pytest.approx(.1)
    assert result["manual"]["plans"][0]["limited"]
    assert "negative_export_price" in result["manual"]["plans"][0]["reasons"]


def test_past_pending_plan_is_missed_and_does_not_add_energy():
    item = plan(start_time=NOW - timedelta(minutes=5), max_runtime_h=1)
    result = run(manual_plans=(item,))
    assert result["end_soc"] == 50
    assert result["manual"]["skipped_count"] == 1
    assert result["manual"]["plans"][0]["reason"] == "manual_start_window_expired"


def test_active_manual_continuation_starts_from_measured_energy_only():
    item = plan(start_time=NOW - timedelta(minutes=5), max_runtime_h=.25,
                lifecycle="active")
    result = run(manual_plans=(item,))
    assert result["totals"]["charge_from_grid_manual_kwh"] == pytest.approx(1 / 6)
    assert result["end_soc"] == pytest.approx((3.6 + .92 / 6) / 7.2 * 100)


def test_overlapping_manual_windows_make_input_invalid():
    a = plan()
    b = plan(id="manual-2", start_time=NOW + timedelta(minutes=10))
    result = run(manual_plans=(a, b))
    assert not result["valid"]
    assert result["manual"]["conflicts_count"] == 1
    assert result["timeline"] == []


@pytest.mark.parametrize("changes", [{"power_w": -5}, {"target_soc": 101},
                                      {"start_time": NOW.replace(tzinfo=None)},
                                      {"action": "invalid"}, {"max_runtime_h": 0}])
def test_invalid_executable_manual_plan_is_reported(changes):
    result = run(manual_plans=(plan(**changes),))
    assert not result["valid"] and result["manual"]["invalid_count"] == 1


def test_manual_high_power_is_limited_without_inventing_energy():
    result = run(manual_plans=(plan(power_w=10000),))
    assert result["totals"]["charge_from_grid_manual_kwh"] == pytest.approx(.8)
    assert result["manual"]["plans"][0]["limited"]
    assert_conserved(result)


def test_within_quarter_reserve_dip_is_visible_after_manual_recovery():
    # First half: manual household discharge reaches hardware minimum.  Second
    # half: charge restores the software target, so the end alone looks safe.
    a = plan(action="discharge", power_w=3200, target_soc=5, max_runtime_h=.125)
    b = plan(id="manual-2", start_time=NOW + timedelta(minutes=7, seconds=30),
             power_w=3200, target_soc=11, max_runtime_h=.125)
    result = run(home=lambda i: .8 if i == 0 else 0, soc_percent=10,
                 manual_plans=(a, b))
    first = result["timeline"][0]
    assert first["soc_end"] >= 10 - .001
    assert first["min_soc"] == pytest.approx(5)
    assert first["reserve_min_gap_kwh"] > 0
    assert not result["reserve_satisfied"]
    assert result["reserve_breach_count"] == 1
    assert_conserved(result)
