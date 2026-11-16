"""The live Plan72 worker must use the original Alpha84 decision chain.

Checks the real worker entry point and the real downstream candidate bridge,
not just standalone source port or a synthetic three-slot preview.
"""
from datetime import timedelta

from test_plan72_runtime import environment, NOW
from test_alpha84_bundle import bundle


def make_inputs(env, *, trade_enabled=True, home=.0, solar=.0, soc=50.0,
                manual_plans=(), buy=None, sell=None):
    start = NOW.replace(minute=30, second=0, microsecond=0)
    stamps = tuple(start + timedelta(minutes=15 * i) for i in range(288))
    imports = tuple(.10 if buy is not None and i in buy else .40 for i in range(288))
    exports = tuple(.80 if sell is not None and i in sell else .05 for i in range(288))
    params = dict(soc_percent=soc, capacity_kwh=7.2, min_soc_percent=5,
        reserve_percent=5, charge_efficiency=.92, discharge_efficiency=.92,
        max_charge_power_w=3200, max_discharge_power_w=3200,
        minimum_trade_margin=.10, trade_enabled=trade_enabled)
    return env.runtime.Plan72Inputs(now=start,
        home=tuple((t, home) for t in stamps),
        solar=tuple((t, solar) for t in stamps),
        prices=tuple((t, imports[i], exports[i], 'known_pt15m', 15)
                     for i, t in enumerate(stamps)),
        parameters=tuple(sorted(params.items())),
        manual_plans=tuple(tuple(sorted(p.items())) for p in manual_plans),
        source_metadata=(), fingerprint='synthetic-test-snapshot',
        replan_reason='quarterly_normal_updates')


def test_active_worker_preserves_same_price_hour_trade_volume_and_full_chain(environment):
    source = make_inputs(environment, buy=range(4), sell=range(48, 52))
    result = environment.runtime._evaluate(source)
    forecast = [dict(time=t.isoformat(), home_consumption_kwh=0,
             solar_kwh=0, import_price=imp, export_price=exp,
             price_source=kind)
             for t, imp, exp, kind, _ in source.prices]
    expected = bundle.compute_strategy_bundle(forecast, now=source.now,
                                               **dict(source.parameters))
    assert expected['plan72']['auto_plan_72h_grid_trade_charge_kwh'] == 3.2
    assert expected['plan72']['auto_plan_72h_grid_trade_discharge_kwh'] == 3.2
    assert result['action_window_search']['method'] == 'alpha84_energy_allocation_then_grouping'
    assert result['slot_count'] == 288
    assert [r['import_all_in'] for r in result['timeline']] == [p[1] for p in source.prices]
    assert result['action_window_count'] == len(result['action_windows'])
    assert result['observational_only'] is True
    assert result['physical_execution_authority'] is False
    assert result['execution_enabled'] is False
    assert result['execution_buffer_percent'] == 2.0  # original live Alpha84 default
    assert result['execution_reserve_kwh'] == __import__('pytest').approx(.864)
    source_candidates = expected['action_bridge']['auto_bridge_candidates']
    assert len(source_candidates) == 2
    assert all(c['valid'] for c in source_candidates)
    assert len(result['action_windows']) == 2, result['action_window_search']
    # The source chooses the original full 3.2 kWh pair. The original two-
    # minute execution handoff limits both physical windows to 3.093 kWh;
    # Plan72 must derive a new SOC target from the actual previous window,
    # never from Alpha84's stale pre-handoff source target.
    assert sum(r['charge_from_grid_trade_kwh'] for r in result['timeline']) == __import__('pytest').approx(3.093, abs=1e-8)
    assert sum(r['discharge_to_grid_trade_kwh'] for r in result['timeline']) == __import__('pytest').approx(3.093, abs=1e-8)
    assert result['status'] == 'ready'
    assert all(not w['limited'] and not w['energy_shortfall_kwh'] for w in result['action_windows'])
    assert result['action_windows'][1]['command_target_soc'] != source_candidates[1]['target_soc']


def test_worker_handles_distinct_quarter_prices_without_hour_averaging(environment):
    source = make_inputs(environment, buy={2}, sell={30})
    result = environment.runtime._evaluate(source)
    assert result['valid'] is True
    assert result['slot_count'] == 288
    assert result['timeline'][2]['import_all_in'] == .1
    assert result['timeline'][1]['import_all_in'] == .4
    assert result['timeline'][30]['export_all_in'] == .8
    assert result['action_window_search']['method'] == 'alpha84_energy_allocation_then_grouping'


def test_protected_scheduled_sell_affects_trade_selection_before_bridge(environment):
    from datetime import timedelta
    start = NOW.replace(minute=30, second=0, microsecond=0)
    # The best spot sale is unavailable because a due/manual plan owns it.
    # The original best-pair search must select the next eligible later sale,
    # not select the unavailable sale and silently discard the trade afterward.
    reserved = dict(id='slot_2', origin='manual', action='discharge',
        lifecycle_status='scheduled', start_time=(start+timedelta(hours=12)).isoformat(),
        max_runtime_h=1, power_w=300, target_soc=10)
    inp = make_inputs(environment, buy=range(4), sell=range(48,52),
                      manual_plans=[reserved])
    shifted = list(inp.prices)
    shifted = [(t, import_price, .75 if 60<=i<64 else export_price,
                source, resolution) for i,(t,import_price,export_price,source,resolution)
                in enumerate(shifted)]
    from dataclasses import replace
    inp = replace(inp, prices=tuple(shifted))
    result = environment.runtime._evaluate(inp)
    assert result['valid'] is True
    assert result['manual']['accepted_count'] == 1
    assert result['action_window_search']['protected_interval_count'] == 4
    assert not result['action_window_search']['suppressed']
    trade_sales = [w for w in result['action_windows'] if w['purpose']=='trade_discharge']
    assert trade_sales
    assert trade_sales[0]['start_time'] == shifted[60][0].isoformat()
    assert result['totals']['charge_from_grid_manual_kwh'] == 0
    assert result['totals']['discharge_to_grid_manual_kwh'] > 0


def test_manual_charge_changes_safety_allocation_before_grouping(environment):
    start = NOW.replace(minute=30, second=0, microsecond=0)
    from dataclasses import replace
    protected = dict(id='slot_1', origin='manual', action='charge',
         lifecycle_status='pending', start_time=(start+timedelta(hours=18)).isoformat(),
         power_w=100, target_soc=90, max_runtime_h=3)
    inp = make_inputs(environment, trade_enabled=False, home=.15/4,
                       soc=60, manual_plans=[protected])
    price_data=[]
    for i, (t, imp, exp, source, minutes) in enumerate(inp.prices):
        price_data.append((t, .05 if 72<=i<84 else .2 if 84<=i<96 else .5,
                           exp, source, minutes))
    inp=replace(inp,prices=tuple(price_data))
    result=environment.runtime._evaluate(inp)
    assert result['manual']['accepted_count']==1
    assert result['action_window_search']['protected_interval_count']==12
    assert result['action_window_search']['suppressed']==[]
    assert result['totals']['charge_from_grid_manual_kwh'] > 0
    assert result['totals']['charge_from_grid_safety_kwh'] > 6
    protected_begin=protected['start_time']
    protected_end=(start+timedelta(hours=21)).isoformat()
    for w in result['action_windows']:
        assert not (w['start_time'] < protected_end and w['planned_end_time'] > protected_begin)
    assert result['physical_execution_authority'] is False
    assert result['execution_enabled'] is False


def test_worker_diagnoses_pair_separately_from_available_trade_windows(environment):
    trade = environment.runtime._evaluate(make_inputs(environment,
        buy=range(4), sell=range(48,52)))['trade']
    assert trade['source_pair_available']
    assert trade['profitable']
    assert trade['candidate_count'] == 2
    assert trade['accepted_count'] == 2
    assert trade['suppressed_count'] == 0
    waiting = environment.runtime._evaluate(make_inputs(environment,
        buy=None, sell=None, trade_enabled=False))['trade']
    assert waiting['reason'] == 'disabled'
    assert waiting['accepted_count'] == 0
