from copy import deepcopy
import importlib
import pytest
from test_alpha84_bridge_port import package
from test_alpha84_planning_port import quarter_forecast
from test_alpha84_planning_oracle import oracle

bundle = importlib.import_module(package.__name__ + '.alpha84_bundle')


def compute(rows, **changes):
    config = dict(now=oracle.NOW, soc_percent=50, capacity_kwh=7.2,
        min_soc_percent=5, reserve_percent=5, charge_efficiency=.92,
        discharge_efficiency=.92, max_charge_power_w=3200,
        max_discharge_power_w=3200, minimum_trade_margin=.1)
    config.update(changes)
    return bundle.compute_strategy_bundle(rows, **config)


def test_complete_quarter_chain_preserves_prices_and_input():
    rows = quarter_forecast()
    before = deepcopy(rows)
    result = compute(rows)
    assert rows == before
    assert len(result['plan72']['auto_plan_72h_plan']) == 288
    assert result['planner_preview']['planner_preview_best_charge_time'] == rows[2]['time']
    assert result['planner_preview']['planner_preview_best_discharge_time'] == rows[30]['time']
    assert result['action_bridge']['auto_bridge_candidate_count'] == 2
    assert result['physical_execution_authority'] is False
    assert result['execution_enabled'] is False


def test_disabled_trade_is_not_credited_in_soc_route():
    result = compute(quarter_forecast(), trade_enabled=False)
    assert result['plan72']['auto_plan_72h_grid_trade_charge_kwh'] == 0
    assert result['plan72']['auto_plan_72h_grid_trade_discharge_kwh'] == 0
    assert result['action_bridge']['auto_bridge_candidate_count'] == 0


def test_missing_interval_cannot_silently_shift_energy():
    rows = quarter_forecast()
    rows[1]['time'] = rows[2]['time']
    with pytest.raises(ValueError, match='noncontiguous'):
        compute(rows)
