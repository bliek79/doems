"""Alpha84 cheapest-feasible safety selection, adapted to native quarters.

Reference: dummy-os-anker-ems 0.0.1-alpha.84, planner_preview.py's
Alpha80 safety allocator and test_alpha80_cheapest_energy_safety.py.
Window preparation and power quantisation remain DOEMS execution contracts.
"""
import ast
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_plan72_model import NOW, run, prices, assert_conserved


def alpha84_selected_hours(soc, hourly_home, hourly_prices):
    """Execute the actual frozen upstream allocator, not a rewritten oracle."""
    source = (Path(__file__).parent / 'fixtures/alpha84/planner_preview.py').read_bytes()
    assert hashlib.sha256(source).hexdigest() == 'f7f453c6f48dd72514604e2367c69cdefc4fdadad6c7004d5f38647aecb3eb38'
    tree = ast.parse(source)
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.ImportFrom) and node.module in {'const', 'homeassistant.util'})]
    namespace = dict(DEFAULT_BATTERY_CAPACITY_KWH=7.2, MIN_SOC_PERCENT=5,
                     dt_util=SimpleNamespace(UTC=timezone.utc, DEFAULT_TIME_ZONE=timezone.utc,
                                             parse_datetime=datetime.fromisoformat))
    exec(compile(tree, 'frozen_alpha84_planner_preview', 'exec'), namespace)
    forecast = [dict(time=(NOW + timedelta(hours=i)).isoformat(),
                     home_consumption_kwh=hourly_home, solar_kwh=0,
                     import_price=hourly_prices(i), export_price=.05) for i in range(72)]
    preview = namespace['build_planner_preview'](
        forecast, dict(energy_need_valid=True, energy_need_safety_reserve_kwh=.36),
        soc, 92, 92, .1, max_charge_power_w=3200, max_discharge_power_w=3200, now=NOW)
    return {int((datetime.fromisoformat(row['time']) - NOW).total_seconds() // 3600)
            for row in preview['planner_preview_safety_charge_hours']}


def test_existing_cheap_window_must_not_extend_across_expensive_quarters():
    plan = run(home=lambda i: .15 if i < 32 else 0,
               tariff=prices(lambda i: .1 if i < 4 else .2 if 12 <= i < 24 else .6),
               practical_windows=True)
    assert plan['reserve_satisfied']
    assert sum(row['charge_from_grid_safety_kwh']
               for i, row in enumerate(plan['timeline'])
               if not (i < 4 or 12 <= i < 24)) == pytest.approx(0, abs=1e-9)
    assert_conserved(plan)


def test_safety_compaction_does_not_move_energy_across_price_boundaries():
    plan = run(home=.02, soc_percent=10,
               tariff=prices(lambda i: .1 if i % 2 else .5),
               practical_windows=True)
    for window in plan['action_windows']:
        begin = datetime.fromisoformat(window['start_time'])
        end = datetime.fromisoformat(window['planned_end_time'])
        selected = [row['import_all_in'] for row in plan['timeline']
                    if begin <= datetime.fromisoformat(row['start']) < end]
        assert len(set(selected)) == 1
    assert_conserved(plan)


def test_cheaper_future_window_is_used_if_battery_can_safely_reach_it():
    # Alpha84 regression: a cheaper midday valley beats the earlier night dip.
    tariff = prices(lambda i: .1 if 72 <= i < 84 else .2 if 24 <= i < 28 else .45)
    plan = run(home=.15 / 4, soc_percent=60, tariff=tariff, practical_windows=True)
    assert plan['reserve_satisfied']
    assert sum(r['charge_from_grid_safety_kwh'] for r in plan['timeline'][72:84]) > 0
    assert sum(r['charge_from_grid_safety_kwh'] for r in plan['timeline'][24:28]) == 0
    reference = alpha84_selected_hours(60, .15, lambda i: .1 if 18 <= i < 21 else .2 if i == 6 else .45)
    assert reference & {18, 19, 20}
    assert 6 not in reference


def test_earlier_bridge_charge_is_required_when_cheaper_future_is_unreachable():
    plan = run(home=.25 / 4, soc_percent=25,
               tariff=prices(lambda i: .1 if 72 <= i < 76 else .2 if 24 <= i < 28 else .34),
               practical_windows=True)
    if not plan['reserve_satisfied']:
        assert plan['status'] == 'limited' and plan['reason'] == 'remaining_physical_shortfall'
        assert plan['action_window_search']['suppressed_safety_windows']
        assert 0 < plan['remaining_charge_need_kwh'] < .10 / .92
        assert plan['min_soc'] >= plan['hardware_min_soc']
    assert sum(r['charge_from_grid_safety_kwh'] for r in plan['timeline'][24:28]) > 0
    reference = alpha84_selected_hours(25, .25, lambda i: .1 if i == 18 else .2 if i == 6 else .34)
    assert 6 in reference


def test_solar_first_no_grid_charge_when_passive_route_is_safe():
    plan = run(home=.01, solar=.02, practical_windows=True)
    assert plan['action_windows'] == []
    assert plan['totals']['charge_from_grid_safety_kwh'] == 0
