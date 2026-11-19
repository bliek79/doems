"""Full candidate-window selection occurs before the three-slot Bridge preview.

Unlike the original hourly reference, a 15-minute tariff is not constant over an
hour. All distinct quarter prices must contribute to the cheapest feasible
contiguous safety window's cost. This is a strategy property, not a comparison
of distinct live forecasts.
"""
from datetime import timedelta
from test_plan72_model import NOW, run, prices, assert_conserved
from test_alpha84_bundle import bundle


def selected(*, tariff=None, manual_plans=()):
    values = lambda i: .10 if i in (16, 18, 20, 22, 24, 26) else .105 if 16 <= i <= 26 else .27
    return run(home=lambda i: .18 if i < 52 else 0,
               solar=0, soc_percent=60,
               tariff=tariff or prices(values),
               manual_plans=manual_plans,
               practical_windows=True,
               strategy_factory=bundle.compute_strategy_bundle)


def test_alternating_quarter_prices_choose_a_single_contiguous_feasible_charging_window():
    actual = selected()
    assert actual['valid']
    assert actual['slot_count'] == 288
    assert actual['reserve_satisfied']
    assert actual['remaining_charge_need_kwh'] == 0
    windows = actual['action_windows']
    assert len(windows) == 1, [(w['start_time'], w['planned_end_time']) for w in windows]
    assert windows[0]['start_time'] == (NOW + timedelta(minutes=16 * 15)).isoformat()
    assert windows[0]['planned_end_time'] == (NOW + timedelta(minutes=27 * 15)).isoformat()
    assert windows[0]['purpose'] == 'safety_charge'
    assert windows[0]['max_runtime_h'] > 2
    assert windows[0]['physical_execution_authority'] is False
    assert actual['action_window_search']['source_candidate_count'] == 1
    assert_conserved(actual)


def test_manual_protected_quarter_interrupts_candidate_window_before_selection():
    blocked = dict(id='slot_1', action='charge', origin='manual',
                   lifecycle_status='scheduled',
                   start_time=(NOW + timedelta(minutes=19 * 15)).isoformat(),
                   max_runtime_h=.25, power_w=150, target_soc=95)
    actual = selected(manual_plans=[blocked])
    assert actual['valid'], actual
    assert actual['manual']['accepted_count'] == 1
    protected_start = NOW + timedelta(minutes=19*15)
    protected_end = protected_start + timedelta(minutes=15)
    for window in actual['action_windows']:
        assert not (window['start_time'] < protected_end.isoformat()
                    and window['planned_end_time'] > protected_start.isoformat())
    assert_conserved(actual)


def test_very_cheap_future_quarter_cannot_supply_earlier_safety_deadline():
    actual = run(home=lambda i: .3 if i < 8 else 0,
                 tariff=prices(lambda i:.01 if i==12 else .20 if i<=3 else .40),
                 soc_percent=20,practical_windows=True,
                 strategy_factory=bundle.compute_strategy_bundle)
    assert actual['reserve_satisfied'], actual['reason']
    assert all(w['start_time'] < (NOW+timedelta(minutes=12*15)).isoformat()
               for w in actual['action_windows'] if w['purpose']=='safety_charge')
    assert_conserved(actual)


def test_no_new_economic_trade_constraints_or_device_execution():
    actual=selected()
    assert not actual['execution_enabled']
    assert not actual['physical_execution_authority']
    assert actual['trade']['search_method']=='alpha84_best_pair'


def test_unrelated_later_quarter_price_change_does_not_rewrite_earlier_safety_deadline():
    common = dict(home=lambda i: .3 if i < 8 else 0,
                  soc_percent=20, practical_windows=True,
                  strategy_factory=bundle.compute_strategy_bundle)
    price_at = lambda i: .20 if i < 8 else .40
    original = run(tariff=prices(price_at), **common)
    future_only = run(tariff=prices(lambda i: .41 if i == 201 else price_at(i)), **common)
    assert original['reserve_satisfied'] == future_only['reserve_satisfied']
    assert original['remaining_charge_need_kwh'] == future_only['remaining_charge_need_kwh']
    assert [(w['start_time'], w['planned_end_time'], w['requested_energy_kwh'])
            for w in original['action_windows']] == [
                (w['start_time'], w['planned_end_time'], w['requested_energy_kwh'])
                for w in future_only['action_windows']]
    assert_conserved(original)
    assert_conserved(future_only)
