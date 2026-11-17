from datetime import timedelta
from test_plan72_model import run, prices, NOW, assert_conserved
from test_alpha84_bundle import bundle
from test_action_bridge import attach, build


def test_restored_safety_route_reaches_existing_bridge_with_provenance():
    plan = run(home=.15/4, soc_percent=60,
        tariff=prices(lambda i: .1 if 72 <= i < 84 else .45),
        practical_windows=True, strategy_factory=bundle.compute_strategy_bundle)
    assert plan['action_window_search']['method'] == 'alpha84_energy_allocation_then_grouping'
    assert_conserved(plan)
    result = build(attach(plan))
    assert result['valid'], result
    assert result['eligible_candidates']
    assert all(not c['validation_reasons'] for c in result['eligible_candidates'])


def test_manual_plan_is_projected_and_not_replaced_by_automatic_action():
    manual = dict(id='slot_1', action='charge', start_time=(NOW+timedelta(minutes=30)).isoformat(),
                  power_w=500, target_soc=90, max_runtime_h=.5, lifecycle_status='pending')
    plan = run(home=0, manual_plans=[manual], practical_windows=True,
               strategy_factory=bundle.compute_strategy_bundle)
    assert plan['manual']['accepted_count'] == 1
    assert plan['totals']['charge_from_grid_manual_kwh'] > 0
    assert_conserved(plan)


def test_later_manual_target_limited_does_not_suppress_earlier_valid_trades():
    """Source partial/limited != an added blanket Bridge trade strategy ban."""
    manual = dict(id='later', origin='manual', action='charge',
                  lifecycle_status='pending',
                  start_time=(NOW+timedelta(hours=50)).isoformat(),
                  max_runtime_h=.5, power_w=100, target_soc=90)
    tariff = prices(lambda i: .10 if i < 4 else .4,
                    lambda i: .8 if 48<=i<52 else .05)
    plan = run(home=0, soc_percent=50, tariff=tariff, manual_plans=[manual],
               practical_windows=True, trade_enabled=True,
               strategy_factory=bundle.compute_strategy_bundle)
    assert plan['status'] == 'limited'
    assert plan['reason'] == 'manual_plan_limited'
    assert plan['reserve_satisfied']
    assert plan['remaining_charge_need_kwh'] == 0
    result = build(attach(plan))
    assert result['valid'], result
    assert result['status'] == 'limited'
    assert result['reason'] == 'source_plan_limited_noncritical'
    assert [c['action_type'] for c in result['slot_preview']] == ['trade_charge', 'grid_discharge']
    assert all(c['selection_status'] == 'eligible' for c in result['candidates'])
