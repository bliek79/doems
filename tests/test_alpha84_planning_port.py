"""Full-output equivalence of the source port, separate from runtime parity."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_alpha84_planning_oracle import oracle

port = oracle.current('alpha84_planning')


def run_chain(rows, soc, capacity=7.2, minimum=5, *, upstream=False):
    functions = {}
    for module, function in (
        ('energy_need', 'build_energy_need_analysis'),
        ('planner_preview', 'build_planner_preview'),
        ('planner_72h', 'build_72h_plan_preview'),
    ):
        if upstream:
            env = oracle.reference(module)
            env.update(DEFAULT_BATTERY_CAPACITY_KWH=capacity, MIN_SOC_PERCENT=minimum)
            functions[function] = env[function]
        else:
            functions[function] = getattr(port, function)
    kwargs = dict(now=oracle.NOW)
    if not upstream:
        kwargs.update(capacity_kwh=capacity, min_soc_percent=minimum)
    need = functions['build_energy_need_analysis'](rows, soc, 5, **kwargs)
    preview = functions['build_planner_preview'](rows, need, soc, 92, 92, .1,
                                               3200, 3200, **kwargs)
    plan = functions['build_72h_plan_preview'](rows, need, preview, soc, 92, 92,
                                             0, 3200, 3200, **kwargs)
    return need, preview, plan


@pytest.mark.parametrize('scenario', list(oracle.scenarios()))
@pytest.mark.parametrize('capacity,minimum', [(7.2, 5), (7.1, 10)])
def test_all_fields_equal_unchanged_reference(scenario, capacity, minimum):
    rows, soc = oracle.scenarios()[scenario]
    assert run_chain(rows, soc, capacity, minimum) == run_chain(
        rows, soc, capacity, minimum, upstream=True)


def test_independent_battery_configurations_do_not_share_mutable_globals():
    rows, soc = oracle.scenarios()['safety_valley']
    settings = [(7.1, 5), (14.4, 10), (7.2, 5), (7.1, 5)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(lambda config: run_chain(rows, soc, *config), settings))
    expected = [run_chain(rows, soc, *config, upstream=True) for config in settings]
    assert actual == expected


@pytest.mark.parametrize('soc', [5, 12, 95, 100])
def test_solar_and_negative_tariffs_equal_reference(soc):
    rows = oracle.forecast(lambda h: .2 if h % 24 < 8 else .4,
        lambda h: 2.4 if 9 <= h % 24 < 15 else 0,
        lambda h: -.1 if 10 <= h % 24 < 13 else .3,
        lambda h: -.05 if 10 <= h % 24 < 13 else .2)
    assert run_chain(rows, soc) == run_chain(rows, soc, upstream=True)


def quarter_forecast(home=0, solar=0):
    from datetime import timedelta
    return [dict(time=(oracle.NOW + timedelta(minutes=15*i)).isoformat(),
        home_consumption_kwh=home, solar_kwh=solar,
        import_price=.1 if i == 2 else .4,
        export_price=.7 if i == 30 else .05, price_source='known')
        for i in range(288)]


def quarter_chain(rows, now=None):
    kwargs = dict(now=now or oracle.NOW, interval_minutes=15,
                  capacity_kwh=7.2, min_soc_percent=5)
    need = port.build_energy_need_analysis(rows, 50, 5, **kwargs)
    preview = port.build_planner_preview(rows, need, 50, 92, 92, .1,
                                        3200, 3200, **kwargs)
    plan = port.build_72h_plan_preview(rows, need, preview, 50, 92, 92,
                                      0, 3200, 3200, **kwargs)
    return need, preview, plan


def test_native_quarter_prices_select_original_best_pair_rule():
    rows = quarter_forecast()
    _, preview, plan = quarter_chain(rows)
    assert preview['planner_preview_best_charge_time'] == rows[2]['time']
    assert preview['planner_preview_best_discharge_time'] == rows[30]['time']
    assert len(plan['auto_plan_72h_plan']) == 288
    assert plan['auto_plan_72h_grid_trade_charge_kwh'] == .8
    assert plan['auto_plan_72h_grid_trade_discharge_kwh'] == .8
    assert sum(r['charge_from_grid_trade_kwh'] > 0
               for r in plan['auto_plan_72h_plan']) == 1


def test_two_hours_of_usable_solar_do_not_become_two_quarters():
    rows = quarter_forecast(home=.1)
    for i in range(4, 6):
        rows[i]['solar_kwh'] = .2
    for i in range(12, 20):
        rows[i]['solar_kwh'] = .2
    need, _, _ = quarter_chain(rows)
    assert need['energy_need_first_usable_solar'] == rows[12]['time']


def test_partial_quarter_uses_remaining_duration_for_power_limit():
    from datetime import timedelta
    rows = quarter_forecast()
    rows[0]['import_price'] = -.2
    _, preview, plan = quarter_chain(rows, now=oracle.NOW + timedelta(minutes=5))
    assert preview['planner_preview_best_charge_time'] == rows[0]['time']
    assert plan['auto_plan_72h_grid_trade_charge_kwh'] == round(3.2 * 10/60, 3)


def test_equal_quarter_prices_keep_original_one_hour_trade_volume():
    rows = quarter_forecast()
    for i, row in enumerate(rows):
        row['import_price'] = .1 if i < 4 else .4
        row['export_price'] = .8 if 48 <= i < 52 else .05
    _, preview, plan = quarter_chain(rows)
    assert preview['planner_preview_best_charge_time'] == rows[0]['time']
    assert preview['planner_preview_best_discharge_time'] == rows[48]['time']
    assert plan['auto_plan_72h_grid_trade_charge_kwh'] == 3.2
    assert plan['auto_plan_72h_grid_trade_discharge_kwh'] == 3.2
    assert [i for i, r in enumerate(plan['auto_plan_72h_plan'])
            if r['charge_from_grid_trade_kwh'] > 0] == [0, 1, 2, 3]
    assert [i for i, r in enumerate(plan['auto_plan_72h_plan'])
            if r['discharge_to_grid_kwh'] > 0] == [48, 49, 50, 51]


def test_price_change_within_trade_hour_stops_before_more_expensive_quarter():
    rows = quarter_forecast()
    for i, row in enumerate(rows):
        row['import_price'] = .1 if i in (0, 1) else .4
        row['export_price'] = .8 if 48 <= i < 52 else .05
    _, preview, plan = quarter_chain(rows)
    assert preview['planner_preview_best_charge_time'] == rows[0]['time']
    assert plan['auto_plan_72h_grid_trade_charge_kwh'] == 1.6
    assert [i for i, r in enumerate(plan['auto_plan_72h_plan'])
            if r['charge_from_grid_trade_kwh'] > 0] == [0, 1]


def test_quarter_source_does_not_lose_household_energy_by_early_rounding():
    # Four unchanged 0.0375-kWh quarters are one real 0.15-kWh hour.
    # The previous 3-digit *per-quarter* export reported 4*0.037
    # = 0.148 kWh, losing 0.002 kWh each hour before Bridge processing.
    rows = quarter_forecast(home=0.0375)
    _, _, plan = quarter_chain(rows)
    first = plan['auto_plan_72h_plan'][:4]
    assert abs(sum(row['home_consumption_kwh'] for row in first) - .15) < 1e-9
    assert abs(sum(row['discharge_to_home_kwh'] for row in first) - .15) < 1e-9
    assert all(row['home_consumption_kwh'] == .0375 for row in first)
    assert len(plan['auto_plan_72h_plan']) == 288


def test_original_60_minute_source_remains_exact_after_quarter_precision_repair():
    rows, soc = oracle.scenarios()['safety_valley']
    assert run_chain(rows, soc) == run_chain(rows, soc, upstream=True)


def test_quarter_safety_preview_preserves_energy_before_72h_source_handoff():
    # Safety decisions originate in the Alpha84 preview. Rounding each
    # candidate to 0.001 kWh *before* source replay silently changes charge
    # energy and can shift later SOC/deadline decisions.
    rows = quarter_forecast(home=.0375)
    _, preview, _ = quarter_chain(rows)
    selected = preview['planner_preview_safety_charge_hours']
    assert selected, 'fixture must exercise the safety path'
    candidate_total = sum(item['candidate_battery_energy_kwh'] for item in selected)
    assert abs(candidate_total - preview['planner_preview_safety_charge_kwh']) < .0002
    # At 15-minute resolution a source candidate must retain sub-Wh precision
    # where the original allocation requires it; 60-minute parity remains
    # checked independently against frozen original Alpha84 bytes.
    assert any(abs(item['candidate_battery_energy_kwh']
                   - round(item['candidate_battery_energy_kwh'], 3)) > 1e-8
               for item in selected)


def test_h5_1_hour_equivalent_safety_allocation_matches_frozen_alpha84():
    """Compare all 72 decision hours with the byte-verified original policy.

    Source quarter energies/solar and prices are exact expansions of original
    hours. This checks the decision itself, not merely totals or a slot preview.
    """
    from datetime import datetime, timedelta
    rows, soc = oracle.scenarios()['safety_valley']
    original = run_chain(rows, soc, upstream=True)[1]
    quarters = []
    for hour in rows:
        for part in range(4):
            quarter = dict(hour)
            quarter['time'] = (datetime.fromisoformat(hour['time']) +
                               timedelta(minutes=15 * part)).isoformat()
            quarter['home_consumption_kwh'] = hour['home_consumption_kwh'] / 4
            quarter['solar_kwh'] = hour['solar_kwh'] / 4
            quarters.append(quarter)
    kwargs = dict(now=oracle.NOW, interval_minutes=15,
                  capacity_kwh=7.2, min_soc_percent=5)
    need = port.build_energy_need_analysis(quarters, soc, 5, **kwargs)
    preview = port.build_planner_preview(quarters, need, soc, 92, 92, .1,
                                        3200, 3200, **kwargs)
    native_by_hour = {}
    for quarter in preview['planner_preview_safety_charge_hours']:
        hour = datetime.fromisoformat(quarter['time']).replace(minute=0)
        native_by_hour[hour] = (native_by_hour.get(hour, 0.0) +
                                quarter['candidate_battery_energy_kwh'])
    original_by_hour = {
        datetime.fromisoformat(hour['time']):
        hour['candidate_battery_energy_kwh']
        for hour in original['planner_preview_safety_charge_hours']
    }
    assert native_by_hour.keys() == original_by_hour.keys()
    for hour, expected in original_by_hour.items():
        assert abs(native_by_hour[hour] - expected) <= 0.000002, (
            hour, native_by_hour[hour], expected
        )
    assert preview['planner_preview_safety_charge_needed'] == (
        original['planner_preview_safety_charge_needed']
    )
