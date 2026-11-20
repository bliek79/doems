"""H5.3 forensic SOC comparison: instrument source copies in memory only.

The original frozen Alpha84 fixture is hash-verified before executing; the
active DOEMS source is unchanged on disk. The extra debug field exposes exact
(unrounded) SOC at each original/quarter boundary, proving whether 0.1
percentage-point reports are real physical drift or rounding ties.
"""
from __future__ import annotations

import ast
import importlib
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
import types

from verify_alpha84_repaired_chain import compare_case, scenarios
from compare_alpha84_planners import NOW, ROOT, reference, HASHES
import hashlib

def _instrument(original: bool):
    path = (ROOT / "tests/fixtures/alpha84/planner_72h.py" if original
            else ROOT / "custom_components/doems/alpha84_planning.py")
    raw = path.read_bytes()
    if original:
        assert hashlib.sha256(raw).hexdigest() == HASHES["planner_72h"]
    body = raw.decode()
    needle = '"soc_end": round(soc_end, 1),'
    assert body.count(needle) == 1, (path, body.count(needle))
    body = body.replace(needle,
        '"soc_end_h53_unrounded": soc_end,\n                "soc_end": round(soc_end, 1),')
    # The following fields exist only in this in-memory compiled diagnostic.
    body = body.replace('"soc_end_h53_unrounded": soc_end,',
        '"soc_end_h53_unrounded": soc_end, '
        '"soc_end_h53_stored_exact": stored_kwh, '
        '"soc_end_h53_safety_raw_ac": grid_safety_input, '
        '"soc_end_h53_safety_target_stored": safety_target_stored,')
    tree = ast.parse(body)
    if original:
        tree.body = [n for n in tree.body
                     if not (isinstance(n, ast.ImportFrom)
                             and n.module in {"const", "homeassistant.util"})]
        env = reference("planner_72h")
        exec(compile(tree, str(path), "exec"), env)
        return env["build_72h_plan_preview"]
    package_name = "doems_h53_reference"
    if package_name not in sys.modules:
        pkg = types.ModuleType(package_name)
        pkg.__path__ = [str(ROOT/"custom_components/doems")]
        sys.modules[package_name] = pkg
    module = types.ModuleType(package_name + ".alpha84_planning")
    module.__package__ = package_name
    sys.modules[module.__name__] = module
    exec(compile(tree, str(path), "exec"), module.__dict__)
    return module


def analyse_case(name):
    rows, soc = scenarios()[name]
    comparison = compare_case(rows, soc)
    orig_need = reference("energy_need")["build_energy_need_analysis"](rows, soc, 5, now=NOW)
    orig_preview = reference("planner_preview")["build_planner_preview"](
        rows, orig_need, soc, 92, 92, .1, 3200, 3200, now=NOW)
    original = _instrument(True)(rows, orig_need, orig_preview, soc, 92, 92, 0,
                                 3200, 3200, now=NOW)
    native = _instrument(False)
    quarters = comparison["input"]["native_quarters"]
    kwargs = dict(now=NOW, capacity_kwh=7.2, min_soc_percent=5, interval_minutes=15)
    need = native.build_energy_need_analysis(quarters, soc, 5, **kwargs)
    preview = native.build_planner_preview(quarters, need, soc, 92, 92, .1,
                                           3200, 3200, **kwargs)
    quarter_plan = native.build_72h_plan_preview(quarters, need, preview, soc,
                                                92, 92, 0, 3200, 3200, **kwargs)
    original_rows = original["auto_plan_72h_plan"]
    quarter_rows = quarter_plan["auto_plan_72h_plan"]
    assert len(original_rows) == 72 and len(quarter_rows) == 288
    # Debug instrumentation must only add its private field, never modify
    # planned flows, source action timing, or displayed SOC.
    for i, item in enumerate(quarter_rows):
        expected = comparison["source_quarter"]["plan"]["auto_plan_72h_plan"][i]
        assert {k:v for k,v in item.items() if not k.startswith("soc_end_h53_")} == expected, (name,i)
    for i, item in enumerate(original_rows):
        expected = comparison["alpha84"]["plan"]["auto_plan_72h_plan"][i]
        assert {k:v for k,v in item.items() if not k.startswith("soc_end_h53_")} == expected, (name,i)

    divergences = []
    trace = []
    for h in range(72):
        a, b = original_rows[h], quarter_rows[4*h+3]
        delta = b["soc_end_h53_unrounded"] - a["soc_end_h53_unrounded"]
        item = {
            "hour": h, "time": a["time"],
            "raw_original": repr(a["soc_end_h53_unrounded"]),
            "raw_quarter": repr(b["soc_end_h53_unrounded"]),
            "raw_delta_soc_percent": delta,
            "raw_delta_kwh": delta * 7.2/100,
            "rounded_original": a["soc_end"],
            "rounded_quarter": b["soc_end"],
            "source_charge_hour_kwh": round(sum(
                quarter_rows[4*h+i]["charge_from_grid_safety_kwh"] for i in range(4)),9),
            "source_home_hour_kwh": round(sum(
                quarter_rows[4*h+i]["discharge_to_home_kwh"] for i in range(4)),9),
            "frozen_charge_hour_kwh": a["charge_from_grid_safety_kwh"],
            "frozen_raw_charge_hour_ac_kwh": a["soc_end_h53_safety_raw_ac"],
            "quarter_raw_charge_hour_ac_kwh": sum(
                quarter_rows[4*h+i]["soc_end_h53_safety_raw_ac"] for i in range(4)),
            "frozen_raw_stored_end_kwh": a["soc_end_h53_stored_exact"],
            "quarter_raw_stored_end_kwh": b["soc_end_h53_stored_exact"],
            "frozen_home_hour_kwh": a["discharge_to_home_kwh"],
        }
        if h in (18, 19, 20, 21, 26, 57):
            print("RAW_DETAIL", name, "hour",h, "original",
                  json.dumps({k:v for k,v in a.items() if k.startswith("soc_end_h53_")},sort_keys=True),
                  "quarters", json.dumps([
                      {k:v for k,v in quarter_rows[4*h+q].items()
                       if k.startswith("soc_end_h53_")} for q in range(4)],sort_keys=True))
        trace.append(item)
        if a["soc_end"] != b["soc_end"]:
            item["rounding_boundary_case"] = abs(delta) < 1e-9
            divergences.append(item)
    return dict(scenario=name,
                unrounded_soc_max_delta=max(abs(x["raw_delta_soc_percent"]) for x in trace),
                rounded_soc_discrepancies=divergences,
                every_hour=trace,
                expected_source_mismatch_count=comparison["diagnostic"]["hourly_source_difference_count"],
                physical_mismatch_count=comparison["diagnostic"]["source_native_difference_count"])


def main():
    reports = {name:analyse_case(name) for name in scenarios()}
    out = Path("build/h53-source-soc-forensic.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(reports,ensure_ascii=False,indent=2)+"\n")
    for name, report in reports.items():
        print("CASE",name,"SOURCE_REPORTED",len(report["rounded_soc_discrepancies"]),
              "RAW_MAX_DELTA_PERCENT",f'{report["unrounded_soc_max_delta"]:.15g}',
              "SOURCE_VS_PHYSICAL",report["physical_mismatch_count"])
        for x in report["rounded_soc_discrepancies"]:
            print("SOC_DIFF",json.dumps(x,sort_keys=True))
        previous_delta = 0.0
        for x in report["every_hour"]:
            if abs(x["raw_delta_soc_percent"] - previous_delta) > 1e-10:
                print("RAW_SHIFT",json.dumps(x,sort_keys=True))
            previous_delta = x["raw_delta_soc_percent"]
    assert set(reports)==set(scenarios())


if __name__=="__main__":
    main()
