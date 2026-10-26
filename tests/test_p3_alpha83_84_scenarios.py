"""Behavior tests for Alpha83 feasibility and Alpha84 continued slot proposals."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "custom_components/doems/automatic_slot_bridge_model.py"
spec = importlib.util.spec_from_file_location("p3_slot_model", P)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def bundle(windows, *, charge_limit=2400):
    start = datetime(2026, 10, 28, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(288):
        quarter_start = start + timedelta(minutes=15 * i)
        kwh = windows.get(i, 0)
        rows.append({
            "index": i, "start": quarter_start.isoformat(),
            "end": (quarter_start + timedelta(minutes=15)).isoformat(),
            "start_soc_percent": 20, "charge_from_grid_safety_kwh": kwh,
            "charge_from_grid_trade_kwh": 0, "trade_discharge_to_grid_kwh": 0,
            "manual_slots": [],
        })
    return {
        "status": "ready", "valid": True, "native_slots": rows,
        "native_slot_count": 288, "capacity_kwh": 7.1,
        "charge_efficiency_percent": 92, "discharge_efficiency_percent": 92,
        "max_charge_power_w": charge_limit, "max_discharge_power_w": 3500,
    }


NOW = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)


def test_alpha83_limited_one_hour_2400w():
    b = bundle({i: 0.6 for i in range(4)})
    result = model.build_automatic_slot_proposals(b, now=NOW)
    assert result["valid"]
    p = result["proposals"][0]
    assert p["requested_energy_kwh"] == 2.4
    assert p["planned_energy_kwh"] == 2.32
    assert p["energy_shortfall_kwh"] == 0.08
    assert p["power_w"] == 2400
    assert p["target_soc"] < 52


def test_alpha84_limited_plan_keeps_later_independent_plan():
    b = bundle({**{i: 0.6 for i in range(4)}, **{i: 0.15 for i in range(8, 12)}})
    result = model.build_automatic_slot_proposals(b, now=NOW)
    assert result["valid"]
    assert len(result["proposals"]) == 2
    assert result["proposals"][0]["energy_shortfall_kwh"] == 0.08
    assert result["proposals"][1]["energy_shortfall_kwh"] == 0


def test_manual_quarter_fence_keeps_manual_priority():
    b = bundle({i: 0.6 for i in range(4)})
    b["native_slots"][1]["manual_slots"] = [1]
    result = model.build_automatic_slot_proposals(b, now=NOW)
    assert result["valid"]
    assert all(p["requested_energy_kwh"] < 2.4 for p in result["proposals"])


def test_not_safety_trade_charge_is_never_silently_capped():
    b = bundle({})
    for i in range(4):
        b["native_slots"][i]["charge_from_grid_trade_kwh"] = 0.65
    result = model.build_automatic_slot_proposals(b, now=NOW)
    assert result["valid"]
    assert not result["proposals"]
    assert any("automatic_power_above_configured_limit" in r for r in result["rejected"])


def test_invalid_first_window_blocks_later_chronological_proposal():
    b = bundle({**{i: 0.65 for i in range(4)}, **{i: 0.15 for i in range(8, 12)}})
    for i in range(4):
        b["native_slots"][i]["charge_from_grid_trade_kwh"] = b["native_slots"][i].pop("charge_from_grid_safety_kwh")
    result = model.build_automatic_slot_proposals(b, now=NOW)
    assert result["valid"]
    assert not result["proposals"]
    assert result["rejected"]


def test_invalid_later_window_retains_earlier_valid_proposal():
    b = bundle({**{i: 0.15 for i in range(4)}, **{i: 0.65 for i in range(8, 12)}})
    for i in range(8, 12):
        b["native_slots"][i]["charge_from_grid_trade_kwh"] = b["native_slots"][i].pop("charge_from_grid_safety_kwh")
    result = model.build_automatic_slot_proposals(b, now=NOW)
    assert result["valid"]
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["energy_shortfall_kwh"] == 0


def test_three_separate_valid_windows_can_supply_three_proposals():
    windows = {**{i: 0.6 for i in range(4)}, **{i: 0.15 for i in range(8, 12)}, **{i: 0.15 for i in range(16, 20)}}
    result = model.build_automatic_slot_proposals(bundle(windows), now=NOW)
    assert result["valid"]
    assert len(result["proposals"]) == 3
    assert result["proposals"][0]["energy_shortfall_kwh"] == 0.08
