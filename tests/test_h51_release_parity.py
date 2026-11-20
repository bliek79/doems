"""Hard H5.1 acceptance: compare source safety fields with frozen Alpha84."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_alpha84_repaired_chain.py"
spec = importlib.util.spec_from_file_location("h51_release_evidence", SCRIPT)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def test_alpha84_source_safety_hour_energy_matches_for_all_72_hours():
    rows, soc = verify.scenarios()["safety_valley"]
    case = verify.compare_case(rows, soc)
    diffs = [x for x in case["diagnostic"]["hourly_source_differences"]
             if x["field"] == "charge_from_grid_safety_kwh"]
    assert diffs == [], diffs
    assert case["diagnostic"]["candidate_counts"]["source"] == 2
    assert case["diagnostic"]["candidate_counts"]["alpha84"] == 2
    assert case["native_plan72"]["plan"]["physical_execution_authority"] is False
    assert case["native_plan72"]["plan"]["execution_enabled"] is False
