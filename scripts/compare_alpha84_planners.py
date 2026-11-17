"""Run the complete frozen Alpha84 planning chain against DOEMS, without HA.

Exit 1 means non-equivalence, not an accepted regression. No battery or Store
operations are loaded. The report contains every source row and candidate.
Hourly inputs are divided uniformly into four quarters, without changing
hourly energy or prices. Comparisons aggregate DOEMS back to those hours.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 15, 0, tzinfo=timezone.utc)
HASHES = {
    'energy_need': '9d7dd824a0f9e5cb3835705326b4037b1ef45e9b549a17d138bb859cd99e9864',
    'planner_preview': 'f7f453c6f48dd72514604e2367c69cdefc4fdadad6c7004d5f38647aecb3eb38',
    'planner_72h': '71f6247a898ec8c1ffcf765534c83d485c6386fe8ccbdfcc465efa75c632be34',
    'planner_action_bridge': '17488870d97fbebb8cb9611da171df6bac2b16d2b7f0030cf649f64c05c47162',
}


def reference(name):
    raw = (ROOT / 'tests/fixtures/alpha84' / (name + '.py')).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == HASHES[name], name
    tree = ast.parse(raw)
    tree.body = [n for n in tree.body if not (
        isinstance(n, ast.ImportFrom) and n.module in {'const', 'homeassistant.util'})]
    env = dict(DEFAULT_BATTERY_CAPACITY_KWH=7.2, MIN_SOC_PERCENT=5,
               DEFAULT_AUTO_EXECUTION_BUFFER_PERCENT=2,
               DEFAULT_CHARGE_EFFICIENCY_PERCENT=92,
               DEFAULT_DISCHARGE_EFFICIENCY_PERCENT=92,
               MIN_ACTIONABLE_SAFETY_CHARGE_KWH=.1, PLAN_SLOT_COUNT=3,
               dt_util=SimpleNamespace(UTC=timezone.utc, DEFAULT_TIME_ZONE=timezone.utc,
                   parse_datetime=datetime.fromisoformat, utcnow=lambda: NOW))
    exec(compile(tree, str(ROOT / 'tests/fixtures/alpha84' / (name + '.py')), 'exec'), env)
    return env


def current(name):
    spec = importlib.util.spec_from_file_location('parity_' + name,
        ROOT / 'custom_components/doems' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def forecast(home, solar, buy, sell):
    return [dict(time=(NOW + timedelta(hours=i)).isoformat(),
        home_consumption_kwh=home(i), solar_kwh=solar(i),
        import_price=buy(i), export_price=sell(i), price_source='known')
        for i in range(72)]


def compare(rows, soc):
    need = reference('energy_need')['build_energy_need_analysis'](rows, soc, 5, now=NOW)
    preview = reference('planner_preview')['build_planner_preview'](
        rows, need, soc, 92, 92, .1, 3200, 3200, now=NOW)
    # Buffer zero in BOTH engines: isolates strategy from different reserve
    # settings. Alpha84's default additional 2% is not silently included.
    original = reference('planner_72h')['build_72h_plan_preview'](
        rows, need, preview, soc, 92, 92, 0, 3200, 3200, now=NOW)
    original_bridge = reference('planner_action_bridge')['build_planner_action_bridge'](
        dict(original, forecast_ready=True, max_charge_power_w=3200,
             max_discharge_power_w=3200, battery_capacity_kwh=7.2,
             charge_efficiency_percent=92, discharge_efficiency_percent=92), now=NOW)
    home, solar, prices = [], [], []
    for row in rows:
        for q in range(4):
            stamp = datetime.fromisoformat(row['time']) + timedelta(minutes=15*q)
            home.append(dict(start=stamp, energy_kwh=row['home_consumption_kwh']/4))
            solar.append(dict(start=stamp, energy_kwh=row['solar_kwh']/4))
            prices.append(dict(start=stamp, import_all_in=row['import_price'],
                               export_all_in=row['export_price'], kind='known'))
    parameters = dict(capacity_kwh=7.2, min_soc_percent=5, reserve_percent=5,
        charge_efficiency=.92, discharge_efficiency=.92,
        max_charge_power_w=3200, max_discharge_power_w=3200)
    plan = current('planner_72h').calculate_plan72(home, solar, prices, now=NOW,
        soc_percent=soc, **parameters, minimum_trade_margin=.1,
        trade_enabled=True, practical_windows=True)
    plan.update(battery_parameters=parameters, calculated_at=NOW.isoformat(),
                plan_generation=1, input_fingerprint='identical-hourly-input')
    bridge = current('planner_action_bridge').build_action_bridge(plan, now=NOW)
    mismatches = []
    # Source publishes energies to .001 kWh and SOC to .1 percentage point.
    # These are output precision tolerances, never tuned to DOEMS results.
    flows = ('charge_from_solar_kwh', 'charge_from_grid_safety_kwh',
             'charge_from_grid_trade_kwh', 'discharge_to_home_kwh',
             'discharge_to_grid_kwh', 'grid_import_for_home_kwh', 'solar_export_kwh')
    for h, upstream in enumerate(original['auto_plan_72h_plan']):
        quarters = plan['timeline'][h*4:h*4+4]
        for key in (*flows, 'soc_end'):
            actual = quarters[-1][key] if key == 'soc_end' else sum(r[key] for r in quarters)
            tolerance = .05000001 if key == 'soc_end' else .00050001
            if abs(upstream[key] - actual) > tolerance:
                mismatches.append(dict(hour=h, time=upstream['time'], field=key,
                    alpha84=upstream[key], doems=actual, tolerance=tolerance))
    a_count = original_bridge['auto_bridge_candidate_count']
    d_count = bridge['candidate_count']
    if a_count != d_count:
        mismatches.append(dict(field='candidate_count', alpha84=a_count, doems=d_count))
    for index, (upstream, candidate) in enumerate(zip(
            original_bridge['auto_bridge_candidates'], bridge['candidates'])):
        for key in ('action', 'start_time', 'planned_end_time', 'power_w'):
            expected = upstream.get(key)
            if key == 'action':
                expected = {'laden': 'charge', 'ontladen': 'discharge'}.get(expected, expected)
            if expected != candidate.get(key):
                mismatches.append(dict(candidate_index=index, field=key,
                    alpha84=expected, doems=candidate.get(key)))
    return dict(input=dict(now=NOW.isoformat(), soc=soc, parameters=parameters,
                           execution_buffer_percent=0, forecast=rows),
        alpha84=dict(energy_need=need, preview=preview, plan=original, bridge=original_bridge),
        doems=dict(plan=plan, bridge=bridge), mismatches=mismatches,
        equivalent=not mismatches)


def scenarios():
    return {
        'passive_control': (forecast(lambda h: .02, lambda h: 0, lambda h: .3, lambda h: .05), 80),
        'safety_valley': (forecast(lambda h: .15, lambda h: 0,
            lambda h: .1 if 18 <= h < 21 else .2 if h == 6 else .45, lambda h: .05), 60),
        'repeated_trade_opportunities': (forecast(lambda h: 0, lambda h: 0,
            lambda h: .1 if h % 24 < 4 else .35,
            lambda h: .6 if 12 <= h % 24 < 16 else .05), 50),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=list(scenarios()), action='append')
    args = parser.parse_args()
    results = {}
    for name, (rows, soc) in scenarios().items():
        if args.case and name not in args.case:
            continue
        results[name] = compare(rows, soc)
        r = results[name]
        print(name, 'PASS' if r['equivalent'] else 'FAIL',
              'differences=', len(r['mismatches']), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, default=str) + '\n')
    return 0 if all(r['equivalent'] for r in results.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
