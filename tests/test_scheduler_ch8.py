"""Execute the frozen Alpha84 scheduler as an independent selection oracle."""
import importlib.util
import itertools
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import types
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
spec = importlib.util.spec_from_file_location('scheduler_ch8', ROOT/'custom_components/doems/scheduler.py')
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def plan(**changes):
    return dict(dict(action='laden', execution_mode='gepland', start_time=NOW.isoformat(),
        power_w=1000, target_soc=80, max_runtime_h=.25, max_start_delay_min=5,
        lifecycle_status='pending', origin='manual'), **changes)


def automatic(**changes):
    return plan(**dict(dict(origin=model.AUTOMATIC, max_start_delay_min=0,
        planner_identity='window-a', planner_signature='signature-a', source_window_id='window-a',
        source_plan_generation=1, source_input_fingerprint='fingerprint-a',
        planned_end_time=(NOW+timedelta(minutes=15)).isoformat(),
        power_start_time=(NOW+timedelta(minutes=2)).isoformat(),
        command_target_soc=100, projected_end_soc=65), **changes))


def evaluate(plans, now=NOW, **kw):
    complete = {i: plan(action='geen', lifecycle_status='concept') for i in range(1,4)}
    complete.update(plans)
    return model.evaluate(complete, now=now, max_charge_power_w=3200, max_discharge_power_w=3200, **kw)


@pytest.fixture
def oracle(monkeypatch):
    def mod(name, **attrs):
        m=types.ModuleType(name);m.__path__=[];m.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, m);return m
    mod('homeassistant');mod('homeassistant.util')
    mod('homeassistant.util.dt', now=lambda: NOW, parse_datetime=datetime.fromisoformat,
        DEFAULT_TIME_ZONE=timezone.utc)
    mod('alpha84_scheduler_oracle');mod('alpha84_scheduler_oracle.const', PLAN_SLOT_COUNT=3)
    mod('alpha84_scheduler_oracle.plan_store', AnkerEmsPlanStore=object)
    name='alpha84_scheduler_oracle.scheduler'
    spec=importlib.util.spec_from_file_location(name,ROOT/'tests/fixtures/alpha84/scheduler.py')
    m=importlib.util.module_from_spec(spec);monkeypatch.setitem(sys.modules,name,m);spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize('cases', list(itertools.product(
    ['empty','direct','due','earlier','future','expired','concept','active'], repeat=3)))
def test_exact_alpha84_selection_parity(oracle, cases):
    def fixture(case):
        return {'empty':plan(action='geen'), 'direct':plan(execution_mode='direct'),
                'due':plan(), 'earlier':plan(start_time=(NOW-timedelta(minutes=2)).isoformat()),
                'future':plan(start_time=(NOW+timedelta(minutes=2)).isoformat()),
                'expired':plan(start_time=(NOW-timedelta(minutes=6)).isoformat()),
                'concept':plan(lifecycle_status='concept'),
                'active':plan(lifecycle_status='actief')}[case]
    plans={i:fixture(case) for i,case in enumerate(cases,1)}
    original=oracle.AnkerEmsScheduler(types.SimpleNamespace(get_plan=lambda i: deepcopy(plans[i]))).evaluate(3200,3200,now=NOW)
    actual=evaluate(plans)
    for field in ('scheduler_selected_slot','scheduler_selected_action','scheduler_status',
                  'scheduler_ready','scheduler_next_future_slot','scheduler_next_future_start'):
        assert actual[field]==original[field], (cases,field)
    assert {i:d['status'] for i,d in actual['scheduler_slots'].items()} == {i:d['status'] for i,d in original['scheduler_slots'].items()}


@pytest.mark.parametrize('offset,ready,status', [(-1,False,'wachtend'),(0,True,'startklaar'),
    (300,True,'startklaar'),(300.000001,False,'verlopen')])
def test_inclusive_manual_start_window(offset,ready,status):
    result=evaluate({1:plan()},now=NOW+timedelta(seconds=offset))
    assert result['scheduler_ready']==ready
    assert result['scheduler_slots'][1]['status']==status


@pytest.mark.parametrize('offset,ready', [(-.000001,False),(0,True),(.000001,False),(10,False)])
def test_zero_automatic_delay_is_not_silently_extended(offset,ready):
    result=evaluate({1:automatic()},now=NOW+timedelta(seconds=offset))
    assert result['scheduler_ready']==ready
    assert result['scheduler_slots'][1]['command_target_soc']==100
    assert result['scheduler_slots'][1]['projected_end_soc']==65


@pytest.mark.parametrize('field,value', [('power_w',True),('power_w',float('nan')),
    ('power_w',float('inf')),('power_w',10**1000),('action',[]),('execution_mode',{}),('lifecycle_status',[]),('power_w',3201),('target_soc',4),('max_runtime_h',.1),
    ('max_start_delay_min',0),('max_start_delay_min',float('nan')),('max_start_delay_min',121),
    ('lifecycle_status','unknown'),('origin','unknown'),('command_target_soc',float('inf'))])
def test_invalid_input_is_not_selected(field,value):
    assert evaluate({1:plan(**{field:value})})['scheduler_slots'][1]['status']=='ongeldig'


@pytest.mark.parametrize('lifecycle',['concept','actief','voltooid','geannuleerd','fout'])
def test_lifecycle_and_observer_do_not_mutate_input(lifecycle):
    plans={1:plan(lifecycle_status=lifecycle)};before=deepcopy(plans)
    r=evaluate(plans)
    assert r['scheduler_selected_slot'] is None
    assert plans==before
    assert r['physical_execution_authority'] is r['execution_enabled'] is False


def test_active_slot_does_not_reinvent_global_execution_gate():
    r=evaluate({1:plan(lifecycle_status='actief'),2:plan()})
    assert r['scheduler_selected_slot']==2 and r['active_slots']==[1]


def test_timezone_offsets_and_dst_fold_are_compared_as_instants():
    amsterdam=ZoneInfo('Europe/Amsterdam')
    early=datetime(2026,10,25,2,30,tzinfo=amsterdam,fold=0)
    later=datetime(2026,10,25,2,30,tzinfo=amsterdam,fold=1)
    r=evaluate({1:plan(start_time=later.isoformat()),2:plan(start_time=early.isoformat(),max_start_delay_min=120)},now=later)
    assert r['scheduler_selected_slot']==2
    r=evaluate({1:plan(start_time='2026-11-04T13:00:00+01:00'),2:plan()},now=NOW)
    assert r['scheduler_selected_slot']==1
    assert evaluate({1:plan(start_time='2026-11-04T12:00:00')})['scheduler_ready'] is False
    with pytest.raises(ValueError,match='timezone_aware'):
        evaluate({1:plan()},now=NOW.replace(tzinfo=None))


def test_end_time_is_hard_and_bad_order_rejected():
    assert evaluate({1:automatic(max_start_delay_min=30)},now=NOW+timedelta(minutes=15))['scheduler_slots'][1]['reason']=='planned_end_reached'
    for fields in ({'planned_end_time':NOW.isoformat()}, {'power_start_time':(NOW-timedelta(seconds=1)).isoformat()},
                   {'source_plan_generation':None},{'planner_identity':None},{'source_input_fingerprint':None}):
        assert not evaluate({1:automatic(**fields)})['scheduler_ready']


def test_source_blocker_clears_selection_and_diagnoses_all_candidates():
    r=evaluate({1:plan(),2:plan(execution_mode='direct')},source_blocker='source_not_ready')
    assert not r['scheduler_ready'] and r['scheduler_selected_slot'] is None
    assert all(r['scheduler_slots'][i]['reason']=='source_not_ready' for i in (1,2))


def test_alpha84_oracle_is_the_verified_upstream_blob():
    import hashlib
    data=(ROOT/'tests/fixtures/alpha84/scheduler.py').read_bytes()
    assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()=='e95a7354cab59464a573f20b154fbc63fbd9de11'
