"""H5.3 acceptance: classify only the proved real rounding-boundary drift.

This does NOT assert that the physical Plan72 replay matches Alpha84.
Original 60m code must remain frozen; native 15m SOC stays physically
causal and must not be rewritten to imitate a rounded hourly display.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "h53_forensic", ROOT / "scripts" / "diagnose_h53_soc.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_h53_two_display_discrepancies_have_single_subwh_causal_origin():
    report = module.analyse_case("safety_valley")
    trace = report["every_hour"]
    differences = report["rounded_soc_discrepancies"]
    assert len(trace) == 72
    assert [r["hour"] for r in differences] == [26, 57]
    assert [(r["rounded_original"], r["rounded_quarter"])
            for r in differences] == [(84.1, 84.2), (13.9, 14.0)]

    # All preceding hours contain the same stored battery energy, despite
    # differences between intra-hour SOC during charging or discharging.
    assert max(abs(row["raw_delta_kwh"]) for row in trace[:20]) < 1e-10
    change = trace[20]
    assert change["frozen_charge_hour_kwh"] == change["source_charge_hour_kwh"] == .275

    # The original Alpha84 source charges before the whole hour's home load,
    # saturating battery headroom by a tiny amount. Native quarter energy
    # accounts for the intermediate home load, leaving 0.00013043478 extra
    # stored energy. This is not a different cheap-hour selection.
    extra_grid_ac = (change["quarter_raw_charge_hour_ac_kwh"]
                     - change["frozen_raw_charge_hour_ac_kwh"])
    assert 0 < extra_grid_ac < .00015
    assert math.isclose(extra_grid_ac * .92, change["raw_delta_kwh"],
                        abs_tol=1e-10, rel_tol=0)
    assert math.isclose(change["raw_delta_kwh"], .000130434782609,
                        abs_tol=1e-10, rel_tol=0)

    # No growing SOC divergence, no unreported energy creation. A physical
    # trajectory mismatch belongs to H5.6, not permission to fake SOC parity.
    for row in trace[20:]:
        assert math.isclose(row["raw_delta_kwh"], change["raw_delta_kwh"],
                            abs_tol=1e-10, rel_tol=0)
    assert report["expected_source_mismatch_count"] == 2
    assert report["physical_mismatch_count"] > 0


def test_h53_passive_and_trade_source_socs_remain_equal_to_original():
    for scenario in ("passive_control", "repeated_trade_opportunities"):
        report = module.analyse_case(scenario)
        assert report["rounded_soc_discrepancies"] == []
        assert report["unrounded_soc_max_delta"] < 1e-10
        assert report["expected_source_mismatch_count"] == 0
