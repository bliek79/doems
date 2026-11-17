"""Alpha84 decisions must survive DOEMS's physical two-minute handoff.

These are independent quarter-price fixtures: not a demand for identical live
Anker and DOEMS forecasts. The first fixture exposes the real class of error:
a source charge at 14:30 cannot erase the reserve gap already at 14:15.
"""
from datetime import timedelta
from test_plan72_model import NOW, run, prices, assert_conserved
from test_alpha84_bundle import bundle


def _late_charge_case(**changes):
    opts = dict(soc_percent=20, practical_windows=True,
                strategy_factory=bundle.compute_strategy_bundle,
                execution_buffer_percent=2,
                home=lambda i: .07 if i < 16 else 0,
                tariff=prices(lambda i: .09 if i in (5, 8, 10) else .40))
    opts.update(changes)
    return run(**opts)


def test_physical_safety_replay_fixes_precharge_reserve_breach():
    plan = _late_charge_case()
    search = plan['action_window_search']
    assert plan['valid']
    assert search['method'] == 'alpha84_energy_allocation_then_grouping'
    assert search['physical_safety_repair_count'] == 1
    assert search['physical_safety_repairs'][0]['before'] == (NOW + timedelta(minutes=9 * 15)).isoformat()
    # The original selected a 14:30 charge, yet reserve was already breached
    # at 14:15. The original cheapest available preceding quarter is 14:00.
    assert search['physical_safety_repairs'][0]['quarter'] == (NOW + timedelta(minutes=8 * 15)).isoformat()
    assert search['physical_safety_repairs'][0]['import_price'] == .09
    assert plan['reserve_breach_count'] == 0
    assert plan['remaining_charge_need_kwh'] == 0
    assert [w['start_time'] for w in plan['action_windows']] == [
        (NOW + timedelta(minutes=8 * 15)).isoformat(),
        (NOW + timedelta(minutes=10 * 15)).isoformat()]
    assert all(w['action'] == 'charge' and w['purpose'] == 'safety_charge'
               for w in plan['action_windows'])
    assert plan['physical_execution_authority'] is False
    assert plan['execution_enabled'] is False
    assert_conserved(plan)


def test_future_cheapest_quarter_cannot_resolve_earlier_reserve_breach():
    plan = _late_charge_case(tariff=prices(lambda i: .01 if i == 12 else .09 if i == 8 else .40))
    assert plan['reserve_satisfied']
    assert plan['remaining_charge_need_kwh'] == 0
    assert all(x['quarter'] != (NOW + timedelta(minutes=12 * 15)).isoformat()
               for x in plan['action_window_search']['physical_safety_repairs'])
    assert_conserved(plan)


def test_no_new_planner_repair_when_source_physical_route_is_already_safe():
    plan = run(home=0, solar=0, practical_windows=True,
               strategy_factory=bundle.compute_strategy_bundle,
               execution_buffer_percent=2)
    assert plan['action_window_search']['physical_safety_repair_count'] == 0
    assert plan['action_windows'] == []
    assert plan['reserve_satisfied']
    assert plan['execution_enabled'] is False


def test_measured_initial_below_reserve_is_still_reported_and_never_faked_ready():
    plan = run(home=0, soc_percent=2, max_charge_power_w=0,
               practical_windows=True, strategy_factory=bundle.compute_strategy_bundle)
    assert plan['valid']
    assert plan['reserve_breach_count'] > 0
    assert plan['remaining_charge_need_kwh'] > 0
    assert plan['status'] == 'limited'
    assert plan['action_window_search']['physical_safety_repair_count'] == 0


def test_protected_manual_quarter_is_not_reused_by_safety_reconciliation():
    reserved = dict(id='slot_1', origin='manual', action='charge',
                    lifecycle_status='scheduled',
                    start_time=(NOW + timedelta(minutes=8*15)).isoformat(),
                    max_runtime_h=.25, power_w=100, target_soc=70)
    plan = _late_charge_case(manual_plans=[reserved])
    assert plan['manual']['accepted_count'] == 1
    assert plan['totals']['charge_from_grid_manual_kwh'] > 0
    for w in plan['action_windows']:
        assert not ((NOW + timedelta(minutes=8*15)).isoformat() < w['planned_end_time']
                    and (NOW + timedelta(minutes=9*15)).isoformat() > w['start_time'])
    assert_conserved(plan)
