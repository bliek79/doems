"""End-to-end regression for the cross-hour 15-minute safety prefix.

This verifies the actual native Plan72 candidate factory, not only the source
bridge. A physically bounded charge remains visible and is not relabelled ready.
"""
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "verify_alpha84_repaired_chain", ROOT / "scripts/verify_alpha84_repaired_chain.py")
_verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_verify)


def test_full_safety_chain_retains_contiguous_cross_hour_prefix_and_energy():
    original_rows, soc = _verify.scenarios()["safety_valley"]
    report = _verify.compare_case(original_rows, soc)
    plan = report["native_plan72"]["plan"]
    windows = plan["action_windows"]
    assert len(windows) == 2
    # The safety source now follows the original hour-first decisions.
    # Derive the earliest later safety hour from the frozen Alpha84 preview,
    # rather than locking in the earlier DOEMS-only 12:30 start.
    reference_safety = [
        hour["time"] for hour in report["alpha84"]["preview"]["planner_preview_safety_charge_hours"]
        if hour["time"] >= "2026-11-17T00:00:00+00:00"
    ]
    assert reference_safety
    assert windows[1]["start_time"] == min(reference_safety)
    assert windows[1]["planned_end_time"] == "2026-11-18T00:00:00+00:00"
    # The former literal 2.071 kWh included premature per-quarter rounding
    # propagated into source allocation. Instead verify that the actual
    # 288-quarter Alpha84 source request is transferred without energy loss
    # into the single physical window. This is stricter than accepting an
    # arbitrary fixed number after a deliberate precision correction.
    tail = windows[1]
    source_quarters = report["source_quarter"]["plan"]["auto_plan_72h_plan"]
    expected_source = sum(
        row["charge_from_grid_safety_kwh"] for row in source_quarters
        if tail["start_time"] <= row["time"] < tail["planned_end_time"]
    )
    assert abs(tail["requested_energy_kwh"] - expected_source) < .001
    assert plan["valid"] is True
    assert plan["reserve_satisfied"] is True
    assert plan["deadline_reserve_satisfied"] is True
    assert plan["remaining_charge_need_kwh"] == 0
    assert windows[0]["limited"] is True
    assert windows[0]["reason"] == "target_or_capacity_limited"
    assert windows[1]["limited"] is False
    # A limited command must not be hidden by a three-slot preview: it remains
    # observable, with both candidates and their projected energy shortfall.
    assert report["diagnostic"]["candidate_counts"]["source"] == 2
    assert report["diagnostic"]["candidate_counts"]["bridge"] == 2
    assert plan["status"] == "limited"
