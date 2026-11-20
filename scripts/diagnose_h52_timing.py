"""H5.2 observer-only timing evidence: frozen Alpha84 vs DOEMS source vs physical Plan72.

Do not mistake a physical two-minute handoff for a strategic price choice.
No Home Assistant integration, battery command or Store is imported.
"""
from __future__ import annotations

import json
from pathlib import Path

from verify_alpha84_repaired_chain import compare_case, scenarios


def _positive(row, key):
    return float(row.get(key, 0) or 0) > 1e-9


def _safety_slots(rows, *, time_key):
    return [
        {"time": row[time_key],
         "safety_kwh": round(float(row["charge_from_grid_safety_kwh"]), 6),
         "soc_end": round(float(row["soc_end"]), 6)}
        for row in rows if _positive(row, "charge_from_grid_safety_kwh")
    ]


def _hour_safety(rows, *, time_key, is_quarter):
    grouped = {}
    for row in rows:
        stamp = str(row[time_key])
        hour = stamp[:13] + ":00:00" + stamp[19:]
        if not is_quarter:
            hour = stamp
        grouped[hour] = grouped.get(hour, 0.0) + float(row["charge_from_grid_safety_kwh"])
    return {k: round(v, 6) for k, v in sorted(grouped.items()) if v > 1e-9}


def diagnose(name):
    rows, soc = scenarios()[name]
    case = compare_case(rows, soc)
    original = case["alpha84"]["plan"]["auto_plan_72h_plan"]
    source = case["source_quarter"]["plan"]["auto_plan_72h_plan"]
    physical = case["native_plan72"]["plan"]
    native_rows = physical["timeline"]
    before = _hour_safety(original, time_key="time", is_quarter=False)
    after = _hour_safety(source, time_key="time", is_quarter=True)
    actual = _hour_safety(native_rows, time_key="start", is_quarter=True)
    steps = sorted(set(before) | set(after) | set(actual))
    timing = [
        {"hour": hour, "alpha84_kwh": before.get(hour, 0),
         "source_kwh": after.get(hour, 0),
         "physical_kwh": actual.get(hour, 0),
         "source_delta": round(after.get(hour, 0)-before.get(hour, 0), 6),
         "physical_delta": round(actual.get(hour, 0)-after.get(hour, 0), 6)}
        for hour in steps
    ]
    windows = [
        {k: win.get(k) for k in (
            "purpose", "start_time", "power_start_time", "planned_end_time",
            "power_w", "requested_energy_kwh", "planned_energy_kwh",
            "energy_shortfall_kwh", "limited", "reason", "source_quarters")}
        for win in physical["action_windows"]
    ]
    report = {
        "status": "H5_2_DIAGNOSIS_NOT_FINAL_ACCEPTANCE",
        "case": name,
        "original_safety_hours": _safety_slots(original, time_key="time"),
        "source_safety_quarters": _safety_slots(source, time_key="time"),
        "physical_safety_quarters": _safety_slots(native_rows, time_key="start"),
        "safety_by_hour": timing,
        "alpha84_source_candidates": case["alpha84"]["bridge_candidates"],
        "source_candidates": case["source_quarter"]["bridge_candidates"],
        "native_windows": windows,
        "physical_search": physical["action_window_search"],
        "physical_status": physical["status"],
        "physical_reserve_satisfied": physical["reserve_satisfied"],
        "physical_reserve_breach_count": physical["reserve_breach_count"],
        "physical_remaining_charge_need_kwh": physical["remaining_charge_need_kwh"],
        "source_vs_native_differences": case["diagnostic"]["source_vs_physical_differences"],
        "source_vs_original_differences": case["diagnostic"]["hourly_source_differences"],
        "comparison_contract": case["comparison_contract"],
        "execution_disabled": not physical["execution_enabled"]
            and not physical["physical_execution_authority"],
    }
    assert report["execution_disabled"]
    assert len(original) == 72 and len(source) == len(native_rows) == 288
    return report


def main():
    destination = Path("build/h52-safety-timing-diagnostic.json")
    result = diagnose("safety_valley")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n")
    print("H5.2 ANALYSIS ONLY - NOT APPROVED")
    print("STATUS", result["physical_status"], "RESERVE",
          result["physical_reserve_satisfied"], "REPAIR",
          result["physical_search"].get("physical_safety_repair_count"))
    print("WINDOWS", json.dumps(result["native_windows"], sort_keys=True))
    print("SOURCE_CANDIDATES", json.dumps(result["source_candidates"], sort_keys=True, default=str))
    print("ALPHA84_CANDIDATES", json.dumps(result["alpha84_source_candidates"], sort_keys=True, default=str))
    for row in result["safety_by_hour"]:
        print("HOUR", json.dumps(row, sort_keys=True))
    print("DIFFERENCES", len(result["source_vs_original_differences"]),
          len(result["source_vs_native_differences"]))


if __name__ == "__main__":
    main()
