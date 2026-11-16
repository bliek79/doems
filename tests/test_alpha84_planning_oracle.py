"""Verify the differential harness; not a declaration of planner equivalence."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/compare_alpha84_planners.py'
spec = importlib.util.spec_from_file_location('alpha84_parity_harness', SCRIPT)
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def test_all_reference_modules_have_verified_upstream_bytes():
    for name in oracle.HASHES:
        assert oracle.reference(name)


def test_identical_passive_forecast_matches_for_all_72_hours():
    rows, soc = oracle.scenarios()['passive_control']
    result = oracle.compare(rows, soc)
    assert len(result['alpha84']['plan']['auto_plan_72h_plan']) == 72
    assert len(result['doems']['plan']['timeline']) == 288
    assert result['mismatches'] == []
    assert result['equivalent']


def test_trade_reference_uses_original_best_pair_without_doems_expectations():
    rows, soc = oracle.scenarios()['repeated_trade_opportunities']
    need = oracle.reference('energy_need')['build_energy_need_analysis'](
        rows, soc, 5, now=oracle.NOW)
    preview = oracle.reference('planner_preview')['build_planner_preview'](
        rows, need, soc, 92, 92, .1, 3200, 3200, now=oracle.NOW)
    assert preview['planner_preview_best_charge_time'] == rows[0]['time']
    assert preview['planner_preview_best_discharge_time'] == rows[12]['time']
    plan = oracle.reference('planner_72h')['build_72h_plan_preview'](
        rows, need, preview, soc, 92, 92, 0, 3200, 3200, now=oracle.NOW)
    assert plan['auto_plan_72h_grid_trade_charge_kwh'] == 3.2
    assert plan['auto_plan_72h_grid_trade_discharge_kwh'] == 3.2
