"""Practical-window route contracts, including the three failed legacy replays."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
import hashlib

import pytest

from test_plan72_model import run,rows,prices,calculate_plan72,NOW,_module as model,assert_conserved


def practical(**changes):
    return run(practical_windows=True,**changes)


def assert_windows(plan):
    assert plan['valid'] and plan['action_window_contract']=='quarter_windows_v1'
    assert_conserved(plan)
    windows=plan['action_windows']
    assert len(windows)==plan['action_window_count']
    for previous,following in zip(windows,windows[1:]):
        assert datetime.fromisoformat(previous['planned_end_time'])<=datetime.fromisoformat(following['start_time'])
    for w in windows:
        start,end=map(datetime.fromisoformat,(w['start_time'],w['planned_end_time']))
        assert start.minute%15==end.minute%15==0
        assert not start.second and not end.second
        assert .25<=w['max_runtime_h']<=12
        assert datetime.fromisoformat(w['power_start_time'])-start==timedelta(minutes=2)
        assert 100<=w['power_w']<=3200
        assert w['power_w']/10==pytest.approx(round(w['power_w']/10))
        assert w['requested_energy_kwh']==pytest.approx(w['planned_energy_kwh']+w['energy_shortfall_kwh'])
        assert w['physical_execution_authority'] is False
        matching=[s for r in plan['timeline'] for s in r['segments'] if s.get('window_id')==w['id']]
        preparation=[s for s in matching if s['action'].endswith('_preparation')]
        assert sum(s['duration_hours'] for s in preparation)==pytest.approx(2/60)
        assert all(s['battery_power_w']==0 and s['stored_start_kwh']==s['stored_end_kwh'] for s in preparation)
        powered=[s for s in matching if s['action'] in {'safety_charge','trade_charge','trade_discharge'}]
        assert w['projected_power_duration_h']==pytest.approx(sum(s['duration_hours'] for s in powered))
        assert w['target_soc']==pytest.approx(powered[-1]['stored_end_kwh']/7.2*100)
        assert w['planned_energy_kwh']==pytest.approx(sum(abs(s['battery_power_w'])*s['duration_hours']/1000 for s in powered))


@pytest.mark.parametrize('case,home,solar',[
    ('constant',.15,0.),
    ('variable',lambda i:.15 if i%96<48 else .08,lambda i:.2 if 32<=i%96<48 else 0.),
    ('low',.02,0.),
])
def test_three_original_route_conflicts_now_have_complete_consistent_windows(case,home,solar):
    plan=practical(home=home,solar=solar,tariff=prices(lambda i:.1 if i%96<24 else .3))
    assert_windows(plan)
    assert plan['status']=='ready'
    assert plan['reserve_satisfied'] and plan['reserve_breach_count']==0
    assert plan['remaining_charge_need_kwh']<=plan['remaining_charge_need_tolerance_kwh']
    # Fewer physical windows, without a three-slot/full-horizon action cap.
    assert 0<plan['action_window_count']<20
    assert all(w['projected_power_duration_h']>=13/60-1e-6 for w in plan['action_windows'])
    assert not plan['action_window_search']['search_limited']


def test_preparation_is_fixed_zero_not_fictitious_battery_cover_or_pv_storage():
    stamps=[NOW+timedelta(minutes=15*i) for i in range(288)]
    battery=model._Battery(7.2,3.6,.36,.72,.92,.92,3.2,3.2)
    w=model._Window('probe','charge','safety',NOW,NOW+timedelta(minutes=15),1.,7.2)
    for home,solar in ((.15,0.),(.05,.2)):
        m=model._Model(stamps,[home]*288,[solar]*288,[(.3,.05,'known')]*288,battery,[])
        trace,_=m.simulate({},windows=[w],detail=True)
        prep=trace[0]['segments'][0]
        assert prep['action']=='safety_preparation'
        assert prep['stored_start_kwh']==prep['stored_end_kwh']==3.6
        assert prep['charge_from_solar_kwh']==0
        assert prep['discharge_to_home_kwh']==0
        assert prep['grid_import_for_home_kwh']==pytest.approx(max(0,home-solar)*4*2/60)
        assert prep['solar_export_kwh']==pytest.approx(max(0,solar-home)*4*2/60)


def test_exact_published_commands_reproduce_the_published_route():
    plan=practical(home=.02)
    commands=[model._Window(w['id'],w['action'],'safety' if w['purpose']=='safety_charge' else 'trade',
        datetime.fromisoformat(w['start_time']),datetime.fromisoformat(w['planned_end_time']),
        w['power_w']/1000,w['target_soc']/100*7.2) for w in plan['action_windows']]
    stamps=[NOW+timedelta(minutes=15*i) for i in range(288)]
    b=model._Battery(7.2,3.6,.36,.72,.92,.92,3.2,3.2)
    replay=model._Model(stamps,[.02]*288,[0.]*288,[(.3,.05,'forecast')]*288,b,[])
    trace,_=replay.simulate({},windows=commands,detail=True)
    for expected,actual in zip(plan['timeline'],trace):
        assert actual['soc_end']==pytest.approx(expected['soc_end'],abs=1e-7)
        for flow in model._FLOWS:
            assert actual[flow]==pytest.approx(expected[flow],abs=1e-8)


def test_no_need_is_idle_without_windows_or_extra_entities():
    plan=practical(home=0,solar=0)
    assert plan['status']=='ready' and plan['action_windows']==[]
    assert plan['totals']['charge_from_grid_safety_kwh']==0


def test_impossible_power_budget_is_visible_no_pulse_fallback():
    plan=practical(home=.3,soc_percent=10,max_charge_power_w=90)
    assert plan['valid'] and plan['status']=='limited'
    assert plan['reserve_breach_count']>0
    assert plan['action_windows']==[]
    assert plan['action_window_search']['reason']=='no_representable_charge_power'
    assert plan['remaining_charge_need_kwh']>0


def test_infeasible_initial_reserve_does_not_hide_later_feasible_recovery():
    plan=practical(home=.02,soc_percent=5)
    assert plan['valid'] and plan['status']=='limited'
    assert plan['reserve_breach_count']>0
    assert any(w['purpose']=='safety_charge' for w in plan['action_windows'])
    assert_windows(plan)


def test_manual_overlap_is_never_replaced_by_automatic_window():
    manual=dict(id='user',action='charge',start_time=(NOW+timedelta(hours=3)).isoformat(),
                power_w=1000,target_soc=80,max_runtime_h=.5,lifecycle_status='pending')
    plan=practical(home=.03,manual_plans=[manual])
    assert plan['manual']['accepted_count']==1
    start=datetime.fromisoformat(manual['start_time']);end=start+timedelta(hours=.5)
    assert all(not(datetime.fromisoformat(w['start_time'])<end and datetime.fromisoformat(w['planned_end_time'])>start) for w in plan['action_windows'])
    assert_conserved(plan)


def test_profitable_export_uses_full_power_phase_and_preserves_fixed_route_reserve():
    baseline=practical(home=0,tariff=prices(.1,.6))
    traded=practical(home=0,tariff=prices(.1,.6),trade_enabled=True)
    assert_windows(traded)
    assert traded['trade']['profitable'] and traded['trade']['accepted_count']>0
    assert traded['reserve_satisfied']
    assert all(w['projected_power_duration_h']==pytest.approx(w['planned_power_duration_h'],abs=1e-7) for w in traded['action_windows'])
    savings=sum(r['cost'] for r in baseline['timeline'])-sum(r['cost'] for r in traded['timeline'])
    assert traded['trade']['total_horizon_cost_saving']==pytest.approx(savings)
    assert savings/traded['totals']['discharge_to_grid_trade_kwh']>=.10-1e-6


def test_negative_export_price_never_creates_export_windows():
    plan=practical(tariff=prices(.1,-.1),trade_enabled=True)
    assert plan['totals']['discharge_to_grid_trade_kwh']==0
    assert not any(w['action']=='discharge' for w in plan['action_windows'])


def test_planning_is_deterministic_and_inputs_unchanged():
    home,solar,tariff=rows(.02),rows(0),prices(.3,.05)
    before=deepcopy((home,solar,tariff))
    kw=dict(now=NOW,soc_percent=50,capacity_kwh=7.2,min_soc_percent=5,reserve_percent=5,
        max_charge_power_w=3200,max_discharge_power_w=3200,trade_enabled=False,practical_windows=True)
    a=calculate_plan72(home,solar,tariff,**kw);b=calculate_plan72(home,solar,tariff,**kw)
    assert a==b and (home,solar,tariff)==before


def test_energy_need_sources_remain_exact_alpha52_blobs():
    root=Path(__file__).resolve().parents[1]/'custom_components/doems'
    for name,expected in {'energy_need.py':'bc10cbb18dd531735e390fe5369466ab4f466087',
                          'energy_need_runtime.py':'3ab25d81615429f51264beb69d4d0064a34f5863'}.items():
        content=(root/name).read_bytes()
        assert hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()==expected


@pytest.mark.parametrize('soc,home,solar,limit',[
    (100,.1,0.,3200),(10,.1,0.,3200),(50,.4,0.,100),
    (95,.04,.1,3200),(20,.03,.02,1500),(50,0.,.1,3200),
])
def test_window_bounds_and_energy_conservation_across_capacity_and_power_cases(soc,home,solar,limit):
    plan=practical(home=home,solar=solar,soc_percent=soc,max_charge_power_w=limit)
    assert_windows(plan)
    assert all(w['power_w']<=limit+1e-7 for w in plan['action_windows'] if w['action']=='charge')
    assert .36-1e-5<=min(r['stored_end_kwh'] for r in plan['timeline'])
    assert max(r['stored_end_kwh'] for r in plan['timeline'])<=7.2+1e-5
    assert plan['projection_count']<7000
    if plan['remaining_charge_need_kwh']>plan['remaining_charge_need_tolerance_kwh']:
        assert plan['status']=='limited'


def test_pair_trade_requires_real_purchase_and_full_duration_sale():
    plan=practical(home=0,soc_percent=10,tariff=prices(lambda i:.02 if i<4 else .3,
        lambda i:.8 if 8<=i<12 else .01),trade_enabled=True)
    assert_windows(plan)
    assert plan['trade']['profitable']
    assert plan['totals']['charge_from_grid_trade_kwh']>0
    assert plan['totals']['discharge_to_grid_trade_kwh']>0
    assert all(w['projected_power_duration_h']>=w['planned_power_duration_h']-1e-7 for w in plan['action_windows'])


def test_optional_trade_preserves_pv_storage_opportunities_and_reserve():
    kw=dict(home=.01,solar=lambda i:.15 if 20<=i%96<40 else 0.,
            tariff=prices(lambda i:.01 if i%96<8 else .3,lambda i:.8 if i%96>60 else .01))
    base=practical(**kw)
    traded=practical(**kw,trade_enabled=True)
    assert_windows(traded)
    for before,after in zip(base['timeline'],traded['timeline']):
        assert after['charge_from_solar_kwh']>=before['charge_from_solar_kwh']-1e-5
        assert after['reserve_min_gap_kwh']<=max(before['reserve_min_gap_kwh'],1e-5)
    assert traded['remaining_charge_need_kwh']<=max(base['remaining_charge_need_kwh'],traded['remaining_charge_need_tolerance_kwh'])
