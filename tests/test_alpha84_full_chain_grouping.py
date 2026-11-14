"""Execute Alpha84's original full-chain grouping, before its slot preview."""
import ast
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_plan72_model import _module as model, NOW


def alpha84():
    raw = (Path(__file__).parent/'fixtures/alpha84/planner_action_bridge.py').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '17488870d97fbebb8cb9611da171df6bac2b16d2b7f0030cf649f64c05c47162'
    tree = ast.parse(raw)
    tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and n.module in {'const','homeassistant.util'})]
    env = dict(DEFAULT_BATTERY_CAPACITY_KWH=100, DEFAULT_CHARGE_EFFICIENCY_PERCENT=92,
               DEFAULT_DISCHARGE_EFFICIENCY_PERCENT=92, MIN_ACTIONABLE_SAFETY_CHARGE_KWH=.1,
               PLAN_SLOT_COUNT=3, dt_util=SimpleNamespace(UTC=timezone.utc,
                   DEFAULT_TIME_ZONE=timezone.utc,parse_datetime=datetime.fromisoformat,utcnow=lambda:NOW))
    exec(compile(tree,'frozen_alpha84_action_bridge','exec'),env)
    return env


def test_eight_source_allocations_form_one_command_before_three_slot_limit():
    stamps=[NOW+timedelta(minutes=15*i) for i in range(288)]
    b=model._Battery(100,20,5,10,.92,.92,3.2,3.2)
    route=model._Model(stamps,[0.]*288,[0.]*288,[(.2,.05,'known')]*288,b,[])
    original=[model._Window(str(i),'charge','safety',NOW+timedelta(hours=i),
                NOW+timedelta(hours=i+1),.3+.1*i,100) for i in range(8)]
    before,_=route.simulate({},windows=original,detail=True)
    rows=[]
    for i,w in enumerate(original):
        energy=sum(r['charge_from_grid_safety_kwh'] for r in before[i*4:(i+1)*4])
        rows.append(dict(time=w.start.isoformat(),soc_start=before[i*4]['soc_start'],
            soc_end=before[(i+1)*4-1]['soc_end'],charge_from_grid_safety_kwh=energy,
            price=.2,price_source='known'))
    reference=alpha84()['build_planner_action_bridge'](dict(auto_plan_72h_plan=rows,
        auto_plan_72h_valid=True,auto_plan_72h_execution_buffer_safe=True,forecast_ready=True,
        max_charge_power_w=3200,max_discharge_power_w=3200,battery_capacity_kwh=100,
        charge_efficiency_percent=92,discharge_efficiency_percent=92), now=NOW)
    grouped,trace=model._group_action_windows(route,original,before)
    assert len(grouped)==reference['auto_bridge_candidate_count']==1
    expected=reference['auto_bridge_candidates'][0]
    actual=grouped[0]
    assert actual.power_kw*1000==expected['power_w']
    assert actual.start.isoformat()==expected['start_time']
    assert actual.end.isoformat()==expected['planned_end_time']
    assert actual.target/b.capacity*100==pytest.approx(expected['target_soc'],abs=.05)
    assert actual.allocation_energy_kwh==pytest.approx(expected['planned_energy_kwh'],abs=.0005)
    assert sum(r['charge_from_grid_safety_kwh'] for r in trace)==pytest.approx(actual.allocation_energy_kwh)


def test_grouping_does_not_cross_gap_direction_or_purpose():
    stamps=[NOW+timedelta(minutes=15*i) for i in range(288)]
    b=model._Battery(100,50,5,10,.92,.92,3.2,3.2)
    route=model._Model(stamps,[0.]*288,[0.]*288,[(.2,.5,'known')]*288,b,[])
    windows=[model._Window(str(i),action,purpose,stamps[i],stamps[i+1],1,100 if action=='charge' else 10)
        for i,action,purpose in [(0,'charge','safety'),(1,'charge','safety'),
                                (3,'charge','safety'),(4,'charge','trade'),(5,'discharge','trade')]]
    before,_=route.simulate({},windows=windows)
    grouped,_=model._group_action_windows(route,windows,before)
    assert [(w.start,w.end) for w in grouped]==[(stamps[0],stamps[2]),(stamps[3],stamps[4]),
                                               (stamps[4],stamps[5]),(stamps[5],stamps[6])]


def test_grouping_includes_tail_beyond_first_three_persistent_slots():
    from test_action_bridge import bridge
    stamps=[NOW+timedelta(minutes=15*i) for i in range(288)]
    b=model._Battery(100,20,5,10,.92,.92,3.2,3.2)
    route=model._Model(stamps,[0.]*288,[0.]*288,[(.2,.05,'known')]*288,b,[])
    windows=[model._Window(str(i),'charge','safety',stamps[i],stamps[i+1],.5,100)
             for group in range(5) for i in range(group*8,group*8+4)]
    source,_=route.simulate({},windows=windows)
    grouped,_=model._group_action_windows(route,windows,source)
    assert len(grouped)==5
    assert all(w.end-w.start==timedelta(hours=1) for w in grouped)
    trace,_=route.simulate({},windows=grouped,detail=True)
    details=model._describe_windows(route,grouped,trace)
    plan=dict(valid=True,status='ready',reserve_satisfied=True,
        action_window_contract='quarter_windows_v1',action_window_count=5,action_windows=details,
        timeline=trace,slot_count=288,horizon_hours=72,start=NOW.isoformat(),
        end=(NOW+timedelta(hours=72)).isoformat(),calculated_at=NOW.isoformat(),
        plan_generation=1,input_fingerprint='whole-chain',battery_parameters=dict(
            capacity_kwh=100,min_soc_percent=5,reserve_percent=5,charge_efficiency=.92,
            discharge_efficiency=.92,max_charge_power_w=3200,max_discharge_power_w=3200))
    result=bridge.build_action_bridge(plan,now=NOW)
    assert result['valid'],result
    assert len(result['eligible_candidates'])==5
    assert len(result['slot_preview'])==3
    assert len(result['overflow_candidates'])==2
    assert result['eligible_candidates'][-1]['planned_end_time']==stamps[36].isoformat()
