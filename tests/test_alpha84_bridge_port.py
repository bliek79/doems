"""Reference grouping and quarter adjacency, before persistent-slot capacity."""
from datetime import timedelta
import importlib.util
import sys
from types import ModuleType
import pytest
from test_alpha84_planning_oracle import oracle
from test_alpha84_planning_port import run_chain

package = ModuleType('alpha84_port_test')
package.__path__ = [str(oracle.ROOT / 'custom_components/doems')]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location('alpha84_port_test.alpha84_action_bridge',
    oracle.ROOT / 'custom_components/doems/alpha84_action_bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def bridge_data(plan):
    return dict(plan, forecast_ready=True, max_charge_power_w=3200,
        max_discharge_power_w=3200, battery_capacity_kwh=7.2,
        charge_efficiency_percent=92, discharge_efficiency_percent=92)


@pytest.mark.parametrize('scenario', list(oracle.scenarios()))
def test_hourly_bridge_all_fields_match_original(scenario):
    rows, soc = oracle.scenarios()[scenario]
    _, _, plan = run_chain(rows, soc)
    data = bridge_data(plan)
    expected = oracle.reference('planner_action_bridge')['build_planner_action_bridge'](
        data, now=oracle.NOW)
    assert bridge.build_planner_action_bridge(data, now=oracle.NOW) == expected


def test_entire_quarter_chain_is_grouped_before_three_slot_preview():
    rows = []
    for group in range(5):
        for q in range(4):
            rows.append(dict(time=(oracle.NOW + timedelta(minutes=15*(group*8+q))).isoformat(),
                soc_start=20, soc_end=30, charge_from_grid_safety_kwh=.2,
                price=.2, price_source='known'))
    result = bridge.build_planner_action_bridge(bridge_data(dict(
        auto_plan_72h_plan=rows, auto_plan_72h_valid=True,
        auto_plan_72h_execution_buffer_safe=True)), now=oracle.NOW, interval_minutes=15)
    candidates = result['auto_bridge_candidates']
    assert len(candidates) == 5
    assert len(result['auto_bridge_slot_preview']) == 3
    assert result['auto_bridge_overflow_count'] == 2
    for i, c in enumerate(candidates):
        assert c['start_time'] == (oracle.NOW + timedelta(hours=i*2)).isoformat()
        assert c['planned_end_time'] == (oracle.NOW + timedelta(hours=i*2+1)).isoformat()
        assert c['handoff_allowance_min'] == 2
        assert c['power_w'] == 830
        assert c['max_runtime_h'] == 1
        assert c['requested_energy_kwh'] == .8


def test_quarter_safety_threshold_keeps_contiguous_hour_allocation():
    # The source's .10 kWh safety cutoff belongs to its hourly interval.
    # Four .030-kWh quarters are one actionable source hour, not four
    # individually rejected safety actions.
    rows = [dict(time=(oracle.NOW + timedelta(minutes=15*q)).isoformat(),
                 soc_start=50, soc_end=55, charge_from_grid_safety_kwh=.03,
                 charge_from_grid_trade_kwh=0, price=.1, price_source='known')
            for q in range(4)]
    result = bridge.build_planner_action_bridge(bridge_data(dict(
        auto_plan_72h_plan=rows, auto_plan_72h_valid=True,
        auto_plan_72h_execution_buffer_safe=True)),
        now=oracle.NOW, interval_minutes=15)
    assert result['auto_bridge_candidate_count'] == 1
    action = result['auto_bridge_candidates'][0]
    assert action['source_hour_count'] == 4
    assert action['requested_energy_kwh'] == .12
    assert action['valid']


def test_subthreshold_complete_hour_does_not_generate_chattering():
    rows = [dict(time=(oracle.NOW + timedelta(minutes=15*q)).isoformat(),
                 soc_start=50, soc_end=52, charge_from_grid_safety_kwh=.02,
                 charge_from_grid_trade_kwh=0, price=.1, price_source='known')
            for q in range(4)]
    result = bridge.build_planner_action_bridge(bridge_data(dict(
        auto_plan_72h_plan=rows, auto_plan_72h_valid=True,
        auto_plan_72h_execution_buffer_safe=True)),
        now=oracle.NOW, interval_minutes=15)
    assert result['auto_bridge_candidate_count'] == 0
    assert result['auto_bridge_suppressed_safety_charge_kwh'] == .08


def test_contiguous_safety_chain_crosses_hour_threshold_before_slot_selection():
    # The first two quarters alone form only 0.091 kWh. Their contribution
    # belongs to the *same* physical safety window as the following hour, so
    # dropping them on the hour boundary changes the SOC route.
    rows = [dict(time=(oracle.NOW + timedelta(minutes=15*q)).isoformat(),
                 soc_start=30, soc_end=40, charge_from_grid_safety_kwh=amount,
                 charge_from_grid_trade_kwh=0, price=.15, price_source='known')
            for q, amount in enumerate((.046, .045, .045, .045, .045, .045))]
    result = bridge.build_planner_action_bridge(bridge_data(dict(
        auto_plan_72h_plan=rows, auto_plan_72h_valid=True,
        auto_plan_72h_execution_buffer_safe=True)),
        now=oracle.NOW, interval_minutes=15)
    assert result['auto_bridge_candidate_count'] == 1
    candidate = result['auto_bridge_candidates'][0]
    assert candidate['start_time'] == oracle.NOW.isoformat()
    assert candidate['source_hour_count'] == 6
    assert candidate['requested_energy_kwh'] == .271
    assert result['auto_bridge_suppressed_safety_charge_kwh'] == 0


def test_disconnected_tiny_safety_segments_cannot_be_joined_by_threshold():
    rows = [dict(time=(oracle.NOW + timedelta(minutes=15*q)).isoformat(),
                 soc_start=30, soc_end=40, charge_from_grid_safety_kwh=amount,
                 charge_from_grid_trade_kwh=0, price=.15, price_source='known')
            for q, amount in enumerate((.055, 0, .055))]
    result = bridge.build_planner_action_bridge(bridge_data(dict(
        auto_plan_72h_plan=rows, auto_plan_72h_valid=True,
        auto_plan_72h_execution_buffer_safe=True)),
        now=oracle.NOW, interval_minutes=15)
    assert result['auto_bridge_candidate_count'] == 0
    assert result['auto_bridge_suppressed_safety_charge_kwh'] == .11
