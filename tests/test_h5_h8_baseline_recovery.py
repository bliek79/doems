"""Hard H5-H8 ownership and energy-handoff regressions.

Uses byte-verified upstream Alpha84 under identical controlled inputs. 64+ SOC
or safety-hour timing differences from 15-minute resolution are separately
reported, never mistaken for identical forecasts or ignored energy loss.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "h5h8_source_differential", ROOT / "scripts/verify_alpha84_repaired_chain.py")
_source = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_source)


def test_original_and_quarter_source_conserve_home_discharge_before_physical_replay():
    hourly, soc = _source.scenarios()["safety_valley"]
    case = _source.compare_case(hourly, soc)
    mismatches = case["diagnostic"]["hourly_source_differences"]
    # The 0.0375 kWh native quarter must not be emitted as 0.037 and then
    # accumulated into a fictitious 0.148-kWh hour.
    lost_energy = [item for item in mismatches if item["field"] == "discharge_to_home_kwh"]
    assert lost_energy == [], lost_energy[:8]
    assert abs(case["source_quarter"]["totals"]["discharge_to_home_kwh"] -
               case["alpha84"]["totals"]["discharge_to_home_kwh"]) < .00001
    assert case["diagnostic"]["candidate_counts"]["source"] == 2
    assert case["diagnostic"]["candidate_counts"]["alpha84"] == 2
    assert case["native_plan72"]["plan"]["physical_execution_authority"] is False


def test_unchanged_hourly_trade_pair_and_roundtrip_not_invented_by_quarter_adapter():
    hourly, soc = _source.scenarios()["repeated_trade_opportunities"]
    case = _source.compare_case(hourly, soc)
    assert case["diagnostic"]["hourly_source_differences"] == []
    assert case["source_quarter"]["totals"]["charge_from_grid_trade_kwh"] == \
        case["alpha84"]["totals"]["charge_from_grid_trade_kwh"]
    assert case["diagnostic"]["candidate_counts"]["source"] == \
        case["diagnostic"]["candidate_counts"]["alpha84"]


def test_live_worker_routes_all_288_quarters_through_only_approved_strategy_factory():
    source = ROOT / "custom_components/doems/planner_72h_runtime.py"
    node = next(n for n in ast.parse(source.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == "_evaluate")
    calculator_calls = [c for c in ast.walk(node)
                        if isinstance(c, ast.Call)
                        and isinstance(c.func, ast.Name)
                        and c.func.id == "calculate_plan72"]
    assert len(calculator_calls) == 1
    kwargs = {x.arg: x.value for x in calculator_calls[0].keywords}
    assert isinstance(kwargs["practical_windows"], ast.Constant)
    assert kwargs["practical_windows"].value is True
    assert isinstance(kwargs["strategy_factory"], ast.Name)
    assert kwargs["strategy_factory"].id == "compute_strategy_bundle"


def test_differential_diagnostic_groups_unresolved_causes_without_auto_approval():
    differences = [
        {"hour": 1, "field": "charge_from_grid_safety_kwh"},
        {"hour": 2, "field": "soc_end"},
        {"hour": 3, "field": "charge_from_grid_trade_kwh"},
        {"hour": 4, "field": "grid_import_for_home_kwh"},
    ]
    grouped = _source.classify_source_differences(differences)
    assert set(grouped) == {
        "safety_allocation_review", "soc_trajectory_review",
        "trade_allocation_review", "other_flow_review",
    }
    assert sum(map(len, grouped.values())) == len(differences)
    assert grouped["safety_allocation_review"] == differences[:1]
    assert grouped["soc_trajectory_review"] == differences[1:2]
    assert grouped["trade_allocation_review"] == differences[2:3]
    assert grouped["other_flow_review"] == differences[3:]


def test_unresolved_safety_valley_source_comparison_is_not_marked_accepted():
    hourly, soc = _source.scenarios()["safety_valley"]
    report = _source.compare_case(hourly, soc)
    diag = report["diagnostic"]
    groups = diag["hourly_source_differences_by_field_group"]
    assert sum(map(len, groups.values())) == diag["hourly_source_difference_count"]
    assert diag["source_strategy_parity_verified"] is (
        diag["hourly_source_difference_count"] == 0
    )
    assert report["comparison_contract"]["accepted"] is False
