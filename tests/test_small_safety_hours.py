"""Alpha84 source-hour actionability and honest SOC after suppression."""
from collections import defaultdict
from datetime import datetime

import pytest
from test_plan72_model import run, assert_conserved
from test_action_bridge import fixture_plan, build, attach
from test_plan72_model import prices


def test_suppressed_hour_reopens_when_replay_reveals_actionable_need():
    # Derived 47%-SOC regression: pre-consumption leaves 0.04 stored kWh
    # above reserve. Banning the next hour after suppressing a small command
    # caused a 0.1928 AC-kWh shortfall and 7.536% minimum SOC in alpha.7.6.
    loads = [.60352] * 4 + [.04] * 5
    plan = run(home=lambda i: loads[i] if i < len(loads) else 0, soc_percent=47,
               tariff=prices(lambda i: .4 if i < 4 else (.2 if i == 4 else .3) if i < 8 else .05),
               practical_windows=True)
    assert plan['status'] == 'ready'
    assert plan['reserve_satisfied'] and plan['reserve_breach_count'] == 0
    assert plan['min_soc'] >= 10
    assert plan['remaining_charge_need_kwh'] <= plan['remaining_charge_need_tolerance_kwh']
    assert plan['action_window_search']['suppressed_safety_windows']
    reopened = plan['action_window_search']['reopened_safety_hours']
    assert reopened and all(hour['source_hour_energy_kwh'] >= .10 for hour in reopened)
    assert sum(row['charge_from_grid_safety_kwh'] for row in plan['timeline'][4:8]) >= .10
    assert plan['timeline'][4]['charge_from_grid_safety_kwh'] >= .10
    assert not plan['action_window_search']['search_limited']
    result = build(attach(plan))
    assert result['valid'] and result['status'] == 'ready'
    assert result['eligible_candidates']
    assert all(c['valid'] for c in result['candidates'])
    assert_conserved(plan)


def test_household_grid_import_is_not_credited_as_purchased_safety_energy():
    plan = run(home=lambda i: .2 if i == 0 else 0, soc_percent=10, practical_windows=True)
    assert plan['action_windows']
    # Alpha84 buys the stored-energy deficit, rather than exploiting the
    # household-import side effect of a minimum-power forced-charge command.
    assert plan['totals']['charge_from_grid_safety_kwh'] >= .2 / .92 - 1e-5
    assert plan['reserve_satisfied']
    assert_conserved(plan)


def test_unactionable_hardware_limit_does_not_leave_fictitious_energy_in_soc():
    plan = run(home=lambda i: .005 if i < 4 else 0, soc_percent=10,
               max_charge_power_w=100, practical_windows=True)
    assert plan['action_window_search']['suppressed_safety_windows']
    assert plan['action_windows'] == []
    assert plan['totals']['charge_from_grid_safety_kwh'] == 0
    assert plan['end_soc'] == pytest.approx((.72 - .02 / .92) / 7.2 * 100)
    assert plan['status'] == 'limited'
    assert plan['remaining_charge_need_kwh'] > 0
    assert not plan['reserve_satisfied']
    assert_conserved(plan)


@pytest.mark.parametrize('energy', [.099, .10, .101])
def test_bridge_checks_explicit_grid_energy_per_hour_at_boundary(energy):
    # 1 kW for 13 minutes: PV supplies the rest of the commanded input.
    solar = (1 - energy / (13 / 60)) / 4
    plan = fixture_plan(kinds=['safety_charge'], solar=solar)
    result = build(plan)
    candidate = result['candidates'][0]
    actual = sum(r['charge_from_grid_safety_kwh'] for r in plan['timeline'][:4])
    assert actual == pytest.approx(energy)
    if actual < .10:
        assert candidate['selection_status'] == 'invalid'
        assert 'small_safety_hour_requires_replanning' in candidate['validation_reasons']
        assert not result['eligible_candidates']
    else:
        assert candidate['selection_status'] == 'eligible'


def test_actionable_hour_survives_and_every_published_safety_hour_meets_threshold():
    plan = run(home=.04, soc_percent=5, practical_windows=True)
    totals = defaultdict(float)
    for row in plan['timeline']:
        totals[datetime.fromisoformat(row['start']).replace(minute=0)] += row['charge_from_grid_safety_kwh']
    safety = [w for w in plan['action_windows'] if w['purpose'] == 'safety_charge']
    assert safety
    for window in safety:
        start = datetime.fromisoformat(window['start_time'])
        assert totals[start.replace(minute=0)] >= .10
    assert_conserved(plan)


def test_small_but_feasible_reserve_deficit_is_repaired_with_actionable_command():
    plan = run(home=lambda i: .005 if i < 4 else 0, soc_percent=10, practical_windows=True)
    assert plan['status'] == 'ready'
    assert plan['reserve_satisfied'] and plan['reserve_breach_count'] == 0
    assert plan['remaining_charge_need_kwh'] <= plan['remaining_charge_need_tolerance_kwh']
    assert plan['action_window_search']['reopened_safety_hours']
    assert plan['totals']['charge_from_grid_safety_kwh'] >= .10
    assert_conserved(plan)
