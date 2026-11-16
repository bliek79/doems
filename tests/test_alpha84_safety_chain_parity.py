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
    assert windows[1]["start_time"] == "2026-11-17T12:30:00+00:00"
    assert windows[1]["planned_end_time"] == "2026-11-18T00:00:00+00:00"
    assert windows[1]["requested_energy_kwh"] == 2.071
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
