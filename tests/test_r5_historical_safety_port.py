"""Executable old-source reference and independent native manual parity."""
from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random

import pytest

from test_alpha7_1_planner_migration_contract import _axis, _load, _plan


def test_native_scalar_replay_matches_full_route_with_manual_targets():
    model = _load('automatic_combined_planner_model')
    safety = _load('safety_planner')
    for seed in range(12):
        rng = random.Random(seed)
        energy, solar = _axis()
        for i in range(288):
            energy[i]['home_kwh'] = rng.uniform(0, .6)
            solar[i]['solar_kwh'] = rng.uniform(0, .8)
        axis, errors = model._validate_time_axis(energy, solar)
        assert not errors
        axis = [{**r, 'prices': {'import_price': .2}} for r in axis]
        t = datetime.fromisoformat(energy[0]['start'])
        plans = [_plan(action='laden' if i != 1 else 'ontladen',
                       start=t + timedelta(hours=3*i, minutes=7),
                       target_soc=70 if i != 1 else 20, slot=i+1,
                       runtime_h=1.5, power_w=1700) for i in range(3)]
        commitments, errors = model._manual_commitments(plans)
        assert not errors
        cap, ce, de = 7.2, .92, .89
        start = rng.uniform(5, 100)
        schedule = {i: rng.uniform(0, .6) for i in range(288) if rng.random() < .3}
        prepared = safety.prepare_safety_slots(axis, commitments, cap, ce, de, 2300, 1800)
        actual, room = safety.replay_safety(prepared, schedule, start, cap, ce, de)
        expected = model._simulate(axis=axis, commitments=commitments,
            start_soc_percent=start, capacity_kwh=cap,
            charge_efficiency=ce, discharge_efficiency=de,
            max_charge_power_w=2300, max_discharge_power_w=1800,
            reserve_floor_end_soc=[10.] * 288, safety=schedule, compact=True)
        assert [round(v, 6) for v in actual] == [r['end_soc_percent'] for r in expected]
        assert [round(v, 6) for v in room] == [r['charge_headroom_kwh'] for r in expected]
        for stop in (0, 47, 287):
            probe, _ = safety.replay_safety(prepared, schedule, start, cap, ce, de, stop=stop)
            assert probe[-1] == actual[stop]


def test_scalar_replay_against_actual_alpha39_source():
    # Execute the actual historical nested function, not a rewritten oracle.
    source = Path(__file__).parent / 'fixtures' / 'alpha39_planner_preview.py.txt'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == '2baf0409efe7e0c53789de43e47c2c7e38afb2c3f7252acd4d2840080f40109d'
    tree = ast.parse(source.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_simulate_safety')
    energy, solar = _axis(home_kwh=.1, solar_kwh=.03)
    model = _load('automatic_combined_planner_model')
    safety = _load('safety_planner')
    axis, _ = model._validate_time_axis(energy, solar)
    axis = [{**r, 'prices': {'import_price': .2}} for r in axis]
    rows = [dict(time=r['start'], solar_kwh=r['solar_kwh'] * 4,
                 home_consumption_kwh=r['home_kwh'] * 4,
                 import_price=.2, export_price=.1, price_source='reference') for r in axis]
    scope = dict(__builtins__=__builtins__, Any=object, price_rows=rows,
                 start_stored_kwh=7.2*.26, minimum_stored_kwh=7.2*.05,
                 DEFAULT_BATTERY_CAPACITY_KWH=7.2, charge_eff=.92, discharge_eff=.92,
                 max_charge_power_w=3500, max_discharge_power_w=3500,
                 _MIN_ENERGY_KWH=.01, _fraction=lambda _: .25,
                 _as_float=lambda v: None if v is None else float(v))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), scope)
    schedule = {i: .36 for i in range(0,288,4)}
    historical = scope['_simulate_safety']({rows[i]['time'].isoformat(): v*.92 for i,v in schedule.items()})
    prepared = safety.prepare_safety_slots(axis, [], 7.2, .92, .92, 3500, 3500)
    soc, room = safety.replay_safety(prepared, schedule, 26, 7.2, .92, .92)
    assert soc == pytest.approx([r['soc_end'] for r in historical], abs=1e-8)
    assert room == pytest.approx([r['remaining_safety_stored_headroom_kwh']/.92 for r in historical], abs=1e-8)


def test_non_linear_safety_allocation_finishes_and_meets_reserve():
    model = _load('automatic_combined_planner_model')
    trace = _load('planner_diagnostics').PlannerDiagnostics('automatic', 1)
    energy, solar = _axis(home_kwh=.1)
    prices = {r['start']: {'import_all_in': .08 if i < 4 else .35,
                         'export_all_in': .02} for i,r in enumerate(energy)}
    trace.start()
    result = model.build_planner_bundle(energy_slots=energy, solar_slots=solar,
        price_by_start=prices, plans=[], start_soc_percent=5, capacity_kwh=7.2,
        stage='automatic', diagnostics=trace)
    trace.finish('completed')
    route = result['automatic']['native_slots']
    assert len(route) == 288
    assert min(r['end_soc_percent'] for r in route) >= 10 - .00001
    assert result['automatic']['safety_schedule_sufficient']
    assert trace.counts['safety_allocation_probes'] > 0
    assert trace.counts['safety_composed_probes'] > 0
    assert trace.counts['safety_replayed_slots'] < 100000


def test_composed_deadline_probe_matches_full_replay_for_random_clamps():
    safety = _load('safety_planner')
    rng = random.Random(481)
    for _ in range(40):
        cap, ce, de = rng.uniform(2, 15), rng.uniform(.7, 1), rng.uniform(.7, 1)
        start = rng.uniform(5, 100)
        slots = [(rng.uniform(0, 1), rng.uniform(0, 1),
                  rng.uniform(.1, 1), rng.uniform(.1, 1), (), .2)
                 for _ in range(288)]
        for i in range(40, 220, 30):
            slots[i] = (*slots[i][:4], ((bool(rng.randrange(2)), rng.uniform(0, .8), rng.uniform(5, 100)),), .2)
        schedule = {i: rng.uniform(0, 1) for i in range(288)}
        route, _ = safety.replay_safety(slots, schedule, start, cap, ce, de)
        deadline = rng.randrange(288)
        probe = safety.prepare_deadline_probe(slots, schedule, route, start, cap, ce, de, deadline)
        for index in {0, deadline, rng.randrange(deadline + 1)}:
            for charge in (0, .2, 1.4):
                changed = dict(schedule, **{})
                changed[index] = charge
                expected, _ = safety.replay_safety(slots, changed, start, cap, ce, de, stop=deadline)
                assert probe(index, charge) == pytest.approx(expected[-1], abs=1e-8)
    manual_slots = [(0., .1, .8, .8, ((True, .2, 70.),), .2)]
    probe = safety.prepare_deadline_probe(manual_slots, {}, [20.], 20., 7.1, .92, .92, 0)
    expected, _ = safety.replay_safety(manual_slots, {0: .4}, 20., 7.1, .92, .92)
    assert probe(0, .4) == pytest.approx(expected[0], abs=1e-8)

