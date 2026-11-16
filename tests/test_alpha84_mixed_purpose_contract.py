"""Combined Alpha84 safety/trade allocation is one physical command."""
from datetime import timedelta
import pytest
from test_action_bridge import bridge, attach, build
from test_plan72_model import NOW, _module as planner, run


def test_mixed_source_charge_reaches_existing_bridge_as_one_command():
    stamps = [NOW + timedelta(minutes=15*i) for i in range(288)]
    start = NOW + timedelta(hours=1)
    end = start + timedelta(hours=1)
    # A genuine two-purpose charge: each quarter contains allocated safety
    # energy and a separate trade portion, without duplicating battery input.
    reference = tuple(((start + timedelta(minutes=15*j)).isoformat(), .10)
                      for j in range(4))
    power_kw = .5
    commanded_ac_kwh = power_kw * (1 - 2/60)
    target = 7.2*.5 + commanded_ac_kwh*.92
    w = planner._Window('mixed_alpha84', 'charge', 'mixed', start, end,
                        power_kw, target, commanded_ac_kwh, reference)
    battery = planner._Battery(7.2, 3.6, .36, .72, .92, .92, 3.2, 3.2)
    m = planner._Model(stamps, [0.]*288, [0.]*288,
                       [(.2,.6,'known')]*288, battery, [])
    timeline, _ = m.simulate({}, windows=[w], detail=True)
    assert abs(sum(t['charge_from_grid_safety_kwh'] for t in timeline) - .4) < 1e-9
    assert sum(t['charge_from_grid_trade_kwh'] for t in timeline) > .08
    assert sum(t['charge_from_grid_manual_kwh'] for t in timeline) == 0
    plan = attach(run())
    plan.update(timeline=timeline, action_window_contract='quarter_windows_v1',
                action_windows=planner._describe_windows(m, [w], timeline),
                action_window_count=1, start_soc=50, end_soc=timeline[-1]['soc_end'])
    result = build(plan)
    assert result['valid'], result
    assert result['slot_preview'][0]['purpose'] == 'mixed_charge'
    assert result['slot_preview'][0]['action_type'] == 'mixed_charge'
    assert result['slot_preview'][0]['flows']['charge_from_grid_safety_kwh'] == pytest.approx(.4)
    assert result['slot_preview'][0]['flows']['charge_from_grid_trade_kwh'] > .08
    assert result['slot_preview'][0]['physical_execution_authority'] is False


def test_due_mixed_charge_replays_split_without_double_counting():
    from test_plan72_model import assert_conserved
    start = NOW + timedelta(hours=1)
    split = [{"time": (start + timedelta(minutes=15*i)).isoformat(),
              "energy_kwh": .10} for i in range(4)]
    intended_kwh = .5 * (1-2/60)
    target_soc = 50 + intended_kwh*.92/7.2*100
    protected = dict(id='slot_1', action='charge', origin='mixed',
        lifecycle_status='active', start_time=start.isoformat(),
        power_start_time=(start+timedelta(minutes=2)).isoformat(),
        max_runtime_h=1, power_w=500, target_soc=target_soc,
        source_safety_quarters=split)
    result = run(home=0, manual_plans=[protected], practical_windows=False)
    assert result['valid'], result
    assert result['manual']['accepted_count'] == 1
    assert result['totals']['charge_from_grid_safety_kwh'] == pytest.approx(.4)
    assert result['totals']['charge_from_grid_trade_kwh'] > .08
    assert result['totals']['charge_from_grid_manual_kwh'] == 0
    assert result['totals']['charge_from_grid_safety_kwh'] + result['totals']['charge_from_grid_trade_kwh'] == pytest.approx(intended_kwh)
    assert_conserved(result)


def test_missing_active_mixed_split_fails_closed():
    from test_plan72_model import run
    protected = dict(id='slot_1', action='charge', origin='mixed',
        lifecycle_status='active', start_time=(NOW + timedelta(hours=1)).isoformat(),
        max_runtime_h=1, power_w=500, target_soc=90)
    result = run(manual_plans=[protected])
    assert result['valid'] is False
    assert result['reason'] == 'invalid_or_overlapping_manual_plans'
