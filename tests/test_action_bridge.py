"""Exact native-window adapter, source provenance and Alpha84 prefix regression."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import importlib.util
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from test_plan72_model import run, rows, prices, NOW, _module as model

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bridge_contract', ROOT/'custom_components/doems/planner_action_bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
P = dict(capacity_kwh=7.2, min_soc_percent=5., reserve_percent=5., charge_efficiency=.92,
         discharge_efficiency=.92, max_charge_power_w=3200., max_discharge_power_w=3200.)


def attach(plan):
    plan.update(battery_parameters=deepcopy(P), plan_generation=1,
                input_fingerprint='a'*64, calculated_at=NOW.isoformat())
    return plan


def fixture_plan(*, limited=False, soc=50., kinds=None, home=0., solar=0.):
    """Exact windows serialized by the original Alpha5.3 model, no mock Bridge math."""
    kinds=kinds or ['safety_charge']*4
    windows=[]
    for i,kind in enumerate(kinds):
        start=NOW+timedelta(hours=i*2)
        origin='safety' if kind=='safety_charge' else 'trade'
        action='discharge' if kind=='trade_discharge' else 'charge'
        target=(soc/100*7.2+.1) if limited and i==0 else (.72 if action=='discharge' else 7.2)
        windows.append(model._Window(str(i),action,origin,start,start+timedelta(minutes=15),1.,target))
    stamps=[NOW+timedelta(minutes=15*i) for i in range(288)]
    battery=model._Battery(7.2,soc/100*7.2,.36,.72,.92,.92,3.2,3.2)
    m=model._Model(stamps,[home]*288,[solar]*288,[(.3,.6,'known')]*288,battery,[])
    trace,_=m.simulate({},windows=windows,detail=True)
    plan=attach(run())
    details=model._describe_windows(m,windows,trace)
    plan.update(timeline=trace, action_window_contract='quarter_windows_v1', action_windows=details,
                action_window_count=len(details), start_soc=soc, end_soc=trace[-1]['soc_end'])
    return plan


def reseal(window):
    window['planner_signature']=bridge._hash({k:v for k,v in window.items() if k != 'planner_signature'})


def build(plan):
    return bridge.build_action_bridge(plan,now=NOW)


@lru_cache
def practical_case(case):
    if case=='safety':
        return attach(run(home=.15,tariff=prices(lambda i:.1 if i%96>=50 else .3),practical_windows=True))
    return attach(run(home=0,soc_percent=10,tariff=prices(lambda i:.02 if i<4 else .3,
        lambda i:.8 if 8<=i<12 else .01),trade_enabled=True,practical_windows=True))


@pytest.mark.parametrize('case',['safety','trade'])
def test_real_alpha53_windows_are_translated_one_for_one_without_route_changes(case):
    plan=deepcopy(practical_case(case)); before=deepcopy(plan)
    result=build(plan)
    assert result['valid'], result
    assert result['candidate_count']==plan['action_window_count']
    assert all(c['valid'] for c in result['candidates'])
    for c,w in zip(result['candidates'],plan['action_windows']):
        for field in ('start_time','power_start_time','planned_end_time','power_w','max_runtime_h',
                      'target_soc','command_target_soc','requested_energy_kwh','planned_energy_kwh',
                      'energy_shortfall_kwh','flows','source_quarters'):
            assert c[field]==w[field]
    assert plan==before
    if case=='trade':
        assert {'trade_charge','grid_discharge'} <= {c['action_type'] for c in result['candidates']}


def test_alpha84_bounded_charge_does_not_block_third_candidate_or_fourth_overflow():
    plan=fixture_plan(limited=True);r=build(plan)
    assert r['valid'] and r['status']=='limited'
    assert len(r['slot_preview'])==3 and len(r['overflow_candidates'])==1
    assert r['held_after_invalid_count']==0 and r['capacity_limited_count']==1
    first=r['candidates'][0]
    assert first['capacity_limited']
    assert first['planned_energy_kwh']==pytest.approx(.1/.92)
    assert first['energy_shortfall_kwh']==pytest.approx(1*13/60-.1/.92)
    assert r['slot_preview'][2]['depends_on_limited_projection']
    assert r['overflow_candidates'][0]['source_window_id']=='3'


def test_two_minute_preparation_is_used_once_not_subtracted_again():
    c=build(fixture_plan())['slot_preview'][0]
    assert c['planned_energy_kwh']==pytest.approx(1*13/60)
    assert c['requested_energy_kwh']==pytest.approx(1*13/60)
    assert c['energy_shortfall_kwh']==pytest.approx(0)
    assert c['max_runtime_h']==.25
    assert c['power_start_time']==(NOW+timedelta(minutes=2)).isoformat()


@pytest.mark.parametrize('index',[0,1,2])
def test_truly_invalid_candidate_preserves_earlier_prefix_holds_entire_tail(index):
    plan=fixture_plan();plan['action_windows'][index]['power_w']=4000
    reseal(plan['action_windows'][index])
    r=build(plan)
    assert len(r['slot_preview'])==index
    assert r['invalid_candidate_count']==1 and r['held_after_invalid_count']==3-index
    assert r['valid']==bool(index)
    assert r['candidates'][index]['validation_reasons']==['invalid_power']
    assert all(c.get('blocked_by_identity') for c in r['candidates'][index+1:])


@pytest.mark.parametrize('change',[
    lambda p:p.update(valid=False),lambda p:p.update(status='calculating'),
    lambda p:p.update(action_window_contract='legacy_segments'),lambda p:p.update(battery_parameters=None),
    lambda p:p.update(plan_generation=True),lambda p:p.update(plan_generation=None),
    lambda p:p.update(input_fingerprint=''),lambda p:p.update(calculated_at='2026-10-29T12:00:00'),
    lambda p:p.update(calculated_at=(NOW+timedelta(seconds=1)).isoformat()),
    lambda p:p['timeline'].pop(),lambda p:p['timeline'][2].update(start=p['timeline'][1]['start']),
    lambda p:p['timeline'][0]['segments'][0].update(duration_hours=.3),
    lambda p:p['battery_parameters'].update(charge_efficiency=float('nan')),
    lambda p:p.update(action_window_count=8),
    lambda p:p['action_windows'].append(deepcopy(p['action_windows'][0])),
    lambda p:p['timeline'][0]['segments'][0].update(window_id='missing'),
])
def test_invalid_source_contract_clears_preview(change):
    p=fixture_plan();change(p);r=build(p)
    assert not r['valid'] and r['slot_preview']==[]


@pytest.mark.parametrize('field,value,reason',[
    ('power_w',float('nan'),'nonfinite_number'),('target_soc',None,None),
    ('energy_shortfall_kwh',.5,'energy_shortfall_mismatch'),('preparation_minutes',0,'preparation_mismatch'),
    ('source_quarters',[],'source_quarters_mismatch'),('planned_energy_kwh',9,'planned_energy_mismatch'),
    ('max_runtime_h',12,'runtime_mismatch'),('projected_end_soc',99,'projected_end_soc_mismatch'),
])
def test_malformed_individual_window_fails_closed(field,value,reason):
    p=fixture_plan();w=p['action_windows'][1];w[field]=value
    if field!='power_w':reseal(w)
    r=build(p)
    assert len(r['slot_preview'])==1 and r['held_after_invalid_count']==2
    assert not r['candidates'][1]['valid']
    if reason and field!='power_w':assert reason in r['candidates'][1]['validation_reasons']


def test_tampered_window_signature_or_mismatched_source_segment_is_rejected():
    p=fixture_plan();p['action_windows'][0]['power_w']=900
    assert build(p)['candidates'][0]['validation_reasons']==['source_window_signature_mismatch']
    p=fixture_plan();p['timeline'][0]['segments'][1]['stored_end_kwh']+=.1
    assert not build(p)['valid']


def test_identity_stable_across_generation_and_soc_revision_signature_changes_with_content():
    p=fixture_plan();a=build(p)['candidates'][0]
    p.update(plan_generation=20,input_fingerprint='b'*64)
    b=build(p)['candidates'][0]
    assert a['planner_identity']==b['planner_identity'] and a['planner_signature']==b['planner_signature']
    c=build(fixture_plan(soc=49))['candidates'][0]
    assert a['planner_identity']==c['planner_identity'] and a['planner_signature']!=c['planner_signature']
    assert a['source_planner_signature']==fixture_plan()['action_windows'][0]['planner_signature']


def test_mixed_grid_and_pv_energy_is_not_mislabelled_as_all_grid():
    r=build(fixture_plan(home=.02,solar=.07))
    assert r['valid']
    c=r['candidates'][0]
    assert c['flows']['charge_from_solar_kwh']>0
    assert c['planned_energy_kwh']>c['explicit_grid_energy_kwh']>0
    assert c['target_soc']==pytest.approx(c['start_soc']+c['planned_energy_kwh']*.92/7.2*100)


def test_export_setpoint_covers_home_plus_grid_no_second_handoff_clipping():
    r=build(fixture_plan(kinds=['trade_discharge'],home=.02))
    assert r['valid'];c=r['candidates'][0]
    assert c['action_type']=='grid_discharge'
    assert c['flows']['discharge_to_home_kwh']>0
    assert c['planned_energy_kwh']==pytest.approx(c['flows']['discharge_to_home_kwh']+c['flows']['discharge_to_grid_kwh'])
    assert c['energy_shortfall_kwh']==pytest.approx(0)


def test_limited_source_exposes_recovery_charge_but_holds_economic_actions():
    p=fixture_plan(kinds=['safety_charge','trade_charge','trade_discharge'])
    p.update(status='limited',reserve_satisfied=False)
    r=build(p)
    assert len(r['slot_preview'])==1 and r['valid']
    assert all(c['selection_status']=='held_source_route_limited' for c in r['candidates'][1:])


def test_idle_passive_route_has_no_candidates():
    p=attach(run(practical_windows=True));r=build(p)
    assert r['valid'] and r['status']=='idle' and not r['candidates']


def test_stale_quarter_is_never_reissued():
    r=bridge.build_action_bridge(fixture_plan(),now=NOW+timedelta(seconds=1))
    assert not r['valid'] and r['reason']=='stale_or_future_plan72_window'


def test_equivalent_timezone_timestamps_keep_identity_and_exact_utc_instants():
    p=fixture_plan();a=build(p)
    for row in p['timeline']:
        for key in ('start','end'):row[key]=datetime.fromisoformat(row[key]).astimezone(ZoneInfo('Europe/Amsterdam')).isoformat()
        for s in row['segments']:
            for key in ('start','end'):s[key]=datetime.fromisoformat(s[key]).astimezone(ZoneInfo('Europe/Amsterdam')).isoformat()
    b=build(p)
    assert b==a


def test_chapters_four_and_five_calculators_and_runtimes_are_frozen_alpha53_blobs():
    expected={'energy_need.py':'bc10cbb18dd531735e390fe5369466ab4f466087',
        'energy_need_runtime.py':'3ab25d81615429f51264beb69d4d0064a34f5863',
        'planner_72h.py':'47dabc7a034476805badd36bba86d72b22341cc2'}
    expected['planner_72h_runtime.py']='8b7fe10b12b62647f12aaa4b3b111e3e92da34e8'
    for name,sha in expected.items():
        data=(ROOT/'custom_components/doems'/name).read_bytes()
        assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==sha


def test_malformed_end_time_is_an_invalid_candidate_without_runtime_exception():
    p=fixture_plan();p['action_windows'][1]['planned_end_time']='bad'
    reseal(p['action_windows'][1])
    r=build(p)
    assert len(r['slot_preview'])==1 and r['held_after_invalid_count']==2


def test_nan_source_is_visible_as_invalid_json_safe_diagnostic():
    import json
    p=fixture_plan();p['action_windows'][1]['power_w']=float('nan')
    r=build(p)
    json.dumps(r,allow_nan=False)
    assert r['candidates'][1]['power_w'] is None


def test_candidates_replayed_as_commands_keep_same_full_route_including_trade():
    for case in ('safety','trade'):
        plan=deepcopy(practical_case(case));r=build(plan)
        assert all(c['valid'] for c in r['candidates'])
        commands=[model._Window(c['source_window_id'],c['action'],
            'safety' if c['purpose']=='safety_charge' else 'trade',
            datetime.fromisoformat(c['start_time']),datetime.fromisoformat(c['planned_end_time']),
            c['power_w']/1000,c['target_soc']/100*7.2) for c in r['candidates']]
        if case=='safety':
            home=[.15]*288; tariff=prices(lambda i:.1 if i%96>=50 else .3);initial=3.6
        else:
            home=[0.]*288;tariff=prices(lambda i:.02 if i<4 else .3,lambda i:.8 if 8<=i<12 else .01);initial=.72
        m=model._Model([NOW+timedelta(minutes=15*i) for i in range(288)],home,[0.]*288,
            [(x['import_all_in'],x['export_all_in'],x['kind']) for x in tariff],
            model._Battery(7.2,initial,.36,.72,.92,.92,3.2,3.2),[])
        trace,_=m.simulate({},windows=commands,detail=True)
        for actual,expected in zip(trace,plan['timeline']):
            assert actual['soc_end']==pytest.approx(expected['soc_end'],abs=1e-7)
            for flow in model._FLOWS:
                assert actual[flow]==pytest.approx(expected[flow],abs=1e-8)


def test_window_overlap_blocks_successor_instead_of_merging_or_extending():
    p=fixture_plan();w=p['action_windows'][1]
    w['start_time']=p['action_windows'][0]['start_time'];reseal(w)
    r=build(p)
    assert len(r['slot_preview'])==1 and r['held_after_invalid_count']==2
    assert 'invalid_or_overlapping_window' in r['candidates'][1]['validation_reasons']


def test_negative_export_price_rejects_export_candidate_without_alternative_dispatch():
    p=fixture_plan(kinds=['trade_discharge']);p['timeline'][0]['export_all_in']=-.01
    assert 'unsafe_trade_discharge' in build(p)['candidates'][0]['validation_reasons']


def test_horizon_crossing_autumn_dst_keeps_288_exact_quarters():
    start=datetime(2026,10,24,22,tzinfo=timezone.utc)
    p=attach(model.calculate_plan72(rows(0,start=start),rows(0,start=start),prices(start=start),
        now=start,soc_percent=50,trade_enabled=False,practical_windows=True,**P))
    p['calculated_at']=start.isoformat()
    assert bridge.build_action_bridge(p,now=start)['valid']
