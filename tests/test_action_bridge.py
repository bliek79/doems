"""Chapter 6 translation, causal-prefix, energy and Alpha84 regressions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bridge_contract', ROOT/'custom_components/doems/planner_action_bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
from test_plan72_model import run, rows, prices, calculate_plan72, NOW

P = dict(capacity_kwh=7.2, min_soc_percent=5., reserve_percent=5.,
         charge_efficiency=.92, discharge_efficiency=.92,
         max_charge_power_w=3200., max_discharge_power_w=3200.)


def attach(plan, parameters=None):
    plan.update(battery_parameters=parameters or deepcopy(P), plan_generation=1,
                input_fingerprint='a'*64, calculated_at=NOW.isoformat())
    return plan


def real_plan(**changes):
    return attach(run(**changes))


def fixture_plan(offsets=(0, 8, 16, 24)):
    """Coherent complete source route with separated forced charge windows."""
    plan = real_plan()
    stored = .72
    for index, row in enumerate(plan['timeline']):
        charge = index in offsets
        energy = .8 if charge else 0.
        after = stored + energy*.92
        segment = dict(start=row['start'], end=row['end'], duration_hours=.25,
                       action='safety_charge' if charge else 'self_consumption',
                       origin='safety' if charge else 'passive', manual_id=None,
                       battery_power_w=3200. if charge else 0., stored_start_kwh=stored,
                       stored_end_kwh=after, target_soc=100. if charge else None,
                       limited=False, reason=None,
                       **{flow:0. for flow in bridge._FLOWS})
        segment['charge_from_grid_safety_kwh'] = energy
        row.update(segments=[segment])
        stored = after
    return plan


def build(plan):
    return bridge.build_action_bridge(plan, now=NOW)


def test_real_plan_exposes_sub_two_minute_segment_without_changing_plan72():
    # Blocking design finding: exact Plan72 segments cannot blindly inherit
    # Alpha84's two-minute subtraction from an entire hourly price window.
    plan = real_plan(home=.15, tariff=prices(lambda i: .1 if i%96>=50 else .3))
    before = deepcopy(plan)
    result = build(plan)
    assert plan == before
    assert result['candidate_count'] >= 3
    assert not result['valid']
    assert result['slot_preview'] == []
    assert result['candidates'][0]['validation_reasons'] == ['no_usable_window_after_handoff']
    assert result['held_after_invalid_count'] == result['candidate_count']-1


def test_no_forced_actions_is_valid_idle_and_never_creates_passive_candidates():
    result = build(real_plan(home=.02, solar=.03))
    assert result['valid'] and result['status'] == 'idle'
    assert result['candidates'] == result['slot_preview'] == []


def test_alpha84_third_candidate_survives_prior_bounded_charge():
    result = build(fixture_plan())
    assert result['valid']
    assert len(result['slot_preview']) == 3
    assert len(result['overflow_candidates']) == 1
    assert result['held_after_invalid_count'] == 0
    assert all(x['valid'] and x['capacity_limited'] for x in result['candidates'])
    assert result['slot_preview'][2]['depends_on_limited_projection'] is True
    # Native quarter: 0.8 kWh request, 13/15 retained after two-minute handoff.
    item = result['slot_preview'][1]
    assert item['planned_energy_kwh'] == pytest.approx(3.2*13/60)
    assert item['energy_shortfall_kwh'] == pytest.approx(3.2*2/60)
    assert item['max_runtime_h'] == .25


def test_original_one_hour_3200w_case_keeps_unrounded_shortfall():
    plan = fixture_plan(offsets=(0,1,2,3,8,16))
    result = build(plan)
    item = result['slot_preview'][0]
    assert len(item['source_segments']) == 4
    assert item['requested_energy_kwh'] == pytest.approx(3.2)
    assert item['planned_energy_kwh'] == pytest.approx(3.2*58/60)
    assert item['energy_shortfall_kwh'] == pytest.approx(3.2*2/60)
    assert len(result['slot_preview']) == 3


@pytest.mark.parametrize('broken_index,expected', [(0,0),(8,1),(16,2)])
def test_invalid_candidate_holds_only_dependent_tail(broken_index, expected):
    plan = fixture_plan()
    plan['timeline'][broken_index]['segments'][0]['stored_start_kwh'] = None
    result = build(plan)
    assert len(result['slot_preview']) == expected
    assert result['invalid_candidate_count'] == 1
    assert result['held_after_invalid_count'] == 3-expected
    assert result['valid'] == bool(expected)
    assert all(x.get('blocked_by_identity') for x in result['candidates'][expected+1:])


@pytest.mark.parametrize('mutate', [
    lambda p:p.update(valid=False),
    lambda p:p.update(status='calculating'),
    lambda p:p.update(battery_parameters=None),
    lambda p:p.update(plan_generation=None),
    lambda p:p.update(input_fingerprint=''),
    lambda p:p.update(calculated_at='2026-10-29T12:00:00'),
    lambda p:p['timeline'].pop(),
    lambda p:p['timeline'][5].update(start=p['timeline'][4]['start']),
    lambda p:p['timeline'][0]['segments'][0].update(duration_hours=.3),
    lambda p:p['battery_parameters'].update(charge_efficiency=float('nan')),
])
def test_invalid_source_contract_fails_closed(mutate):
    plan=fixture_plan(); mutate(plan)
    result=build(plan)
    assert not result['valid']
    assert result['slot_preview'] == []


def test_exact_timezone_instants_and_dst_do_not_change_candidates():
    plan=fixture_plan(); original=build(plan)
    local=ZoneInfo('Europe/Amsterdam')
    for row in plan['timeline']:
        for key in ('start','end'):
            row[key]=datetime.fromisoformat(row[key]).astimezone(local).isoformat()
        for segment in row['segments']:
            for key in ('start','end'):
                segment[key]=datetime.fromisoformat(segment[key]).astimezone(local).isoformat()
    changed=build(plan)
    assert [x['start_time'] for x in original['candidates']] == [x['start_time'] for x in changed['candidates']]
    assert [x['planner_identity'] for x in original['candidates']] == [x['planner_identity'] for x in changed['candidates']]
    # A horizon crossing the actual autumn DST transition remains 288 quarters.
    start=datetime(2026,10,24,22,tzinfo=timezone.utc)
    source=attach(calculate_plan72(rows(0,start=start),rows(0,start=start),prices(start=start),
        now=start,soc_percent=50,trade_enabled=False,**P))
    assert bridge.build_action_bridge(source,now=start)['valid']


def test_identity_stable_signature_sensitive_to_actual_action_not_generation():
    plan=fixture_plan(); a=build(plan)['candidates'][0]
    plan['plan_generation']=10; plan['input_fingerprint']='b'*64
    b=build(plan)['candidates'][0]
    assert a['planner_identity']==b['planner_identity']
    assert a['planner_signature']==b['planner_signature']
    for row in plan['timeline']:
        for segment in row['segments']:
            segment['stored_start_kwh']+=.01;segment['stored_end_kwh']+=.01
    c=build(plan)['candidates'][0]
    assert a['planner_identity']==c['planner_identity']
    assert a['planner_signature']!=c['planner_signature']


def test_mixed_pv_grid_charge_counts_total_battery_energy_and_exact_retained_flows():
    plan=fixture_plan(offsets=(0,1))
    # First quarter includes PV; second entirely grid. Handoff clips first only.
    first=plan['timeline'][0]['segments'][0]
    first.update(charge_from_grid_safety_kwh=.4,charge_from_solar_kwh=.4)
    item=build(plan)['slot_preview'][0]
    assert item['requested_energy_kwh']==pytest.approx(1.6)
    assert item['requested_flows']['charge_from_grid_safety_kwh']==pytest.approx(1.2)
    assert item['planned_flows']['charge_from_solar_kwh']==pytest.approx(.4*13/15)
    assert item['planned_flows']['charge_from_grid_safety_kwh']==pytest.approx(.4*13/15+.8)
    assert item['target_soc']==pytest.approx(10+item['planned_energy_kwh']*.92/7.2*100)


def test_discharge_uses_home_plus_export_and_fails_closed_if_handoff_cannot_fit():
    plan=fixture_plan(offsets=(0,8))
    segment=plan['timeline'][0]['segments'][0]
    segment.update(action='trade_discharge',origin='trade',battery_power_w=-3200.,
                   stored_start_kwh=3.,stored_end_kwh=3-.8/.92,target_soc=10.,
                   charge_from_grid_safety_kwh=0.,discharge_to_home_kwh=.2,
                   discharge_to_grid_kwh=.6,discharge_to_grid_trade_kwh=.6)
    result=build(plan);item=result['candidates'][0]
    assert item['action_type']=='grid_discharge'
    assert item['requested_energy_kwh']==pytest.approx(.8)
    assert item['validation_reasons']==['discharge_energy_does_not_fit_handoff_window']
    assert result['slot_preview']==[] and result['held_after_invalid_count']==1


def test_small_segments_are_not_filtered_by_old_hourly_energy_threshold():
    plan=fixture_plan(offsets=(0,))
    # A low-power synthetic valid source needs <0.10 kWh, but spans 15 minutes.
    segment=plan['timeline'][0]['segments'][0]
    segment.update(battery_power_w=200.,charge_from_grid_safety_kwh=.05,
                   stored_end_kwh=.72+.05*.92)
    result=build(plan)
    assert result['candidate_count']==1 and result['valid']
    assert result['slot_preview'][0]['requested_energy_kwh']==pytest.approx(.05)


def test_valid_limited_plan_keeps_recovery_charge_not_trade():
    plan=fixture_plan(offsets=(0,8))
    segment=plan['timeline'][8]['segments'][0]
    segment.update(action='trade_charge',origin='trade',charge_from_grid_safety_kwh=0.,charge_from_grid_trade_kwh=.8)
    plan.update(status='limited',reserve_satisfied=False)
    result=build(plan)
    assert len(result['slot_preview'])==1
    assert result['candidates'][1]['selection_status']=='held_source_route_limited'


def test_no_stale_plan_or_elapsed_action_is_reissued():
    plan=fixture_plan()
    result=bridge.build_action_bridge(plan,now=NOW+timedelta(seconds=1))
    assert not result['valid'] and result['slot_preview']==[]
    assert result['reason']=='stale_or_future_plan72_window'


def test_passive_gaps_and_purpose_changes_split_actions_manual_never_selected():
    plan=fixture_plan(offsets=(0,1,3,5))
    plan['timeline'][1]['segments'][0].update(action='trade_charge',origin='trade',
       charge_from_grid_trade_kwh=.8,charge_from_grid_safety_kwh=0.)
    plan['timeline'][5]['segments'][0].update(action='manual_charge',origin='manual',manual_id='manual1')
    result=build(plan)
    assert result['candidate_count']==3
    assert [x['action_type'] for x in result['candidates']]==['safety_charge','trade_charge','safety_charge']


def test_protected_calculators_remain_exact_alpha52_blobs():
    expected={'energy_need.py':'bc10cbb18dd531735e390fe5369466ab4f466087',
              'planner_72h.py':'d92fe5e5ca0030c322a68b0db8fb4c3742da39ff'}
    for name,sha in expected.items():
        data=(ROOT/'custom_components/doems'/name).read_bytes()
        assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==sha
