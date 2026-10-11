"""R6 contract: pure 288-quarter bridge without a scheduler or battery command."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load_model():
    if "custom_components" not in sys.modules:
        pkg = types.ModuleType("custom_components")
        pkg.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = pkg
    if "custom_components.doems" not in sys.modules:
        pkg = types.ModuleType("custom_components.doems")
        pkg.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = pkg
    return importlib.import_module("custom_components.doems.automatic_slot_bridge_model")


BASE = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
NOW = BASE - timedelta(hours=1)


def _rows():
    rows = []
    for index in range(288):
        start = BASE + timedelta(minutes=15 * index)
        rows.append({
            "index": index,
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=15)).isoformat(),
            "start_soc_percent": 45.0,
            "charge_from_grid_safety_kwh": 0.0,
            "charge_from_grid_trade_kwh": 0.0,
            "trade_discharge_to_grid_kwh": 0.0,
            "manual_slots": [],
            "manual_overlap_seconds": 0.0,
            "price_source": "known",
            "solar_to_grid_kwh": 0.0,
            "discharge_to_home_kwh": 0.5,
        })
    return rows


def _combined(rows=None):
    return {
        "status": "ready", "valid": True,
        "native_slot_count": 288, "native_slots": rows if rows is not None else _rows(),
        "capacity_kwh": 7.1, "charge_efficiency_percent": 92.0,
        "discharge_efficiency_percent": 92.0,
        "max_charge_power_w": 3500.0, "max_discharge_power_w": 3500.0,
    }


def _three():
    rows = _rows()
    for i in (0, 1):
        rows[i]["charge_from_grid_safety_kwh"] = 0.05
    for i in (8, 9):
        rows[i]["charge_from_grid_trade_kwh"] = 0.08
    for i in (16, 17):
        rows[i]["trade_discharge_to_grid_kwh"] = 0.07
    return _combined(rows)


def test_r6_maps_three_15_min_windows_to_three_independent_proposals():
    model = _load_model()
    result = model.build_automatic_slot_proposals(_three(), now=NOW)
    assert result["valid"] is True
    assert result["source_native_slot_count"] == 288
    assert len(result["proposals"]) == 3
    plans = result["proposals"]
    assert [p["purpose"] for p in plans] == [
        "veiligheidsladen", "handelsladen", "handel_ontladen"
    ]
    assert [p["action"] for p in plans] == ["laden", "laden", "ontladen"]
    assert [p["max_runtime_h"] for p in plans] == [0.5, 0.5, 0.5]
    assert [p["power_w"] for p in plans] == [200.0, 320.0, 280.0]
    assert all(p["origin"] == "automatic_72h_planner" for p in plans)
    assert all(p["max_start_delay_min"] == 10.0 for p in plans)
    assert all(p["execution_mode"] == "gepland" for p in plans)
    assert len(set(p["planner_identity"] for p in plans)) == 3
    assert all(p["all_prices_known"] for p in plans)


def test_r6_soc_target_uses_only_explicit_grid_energy_from_live_capacity():
    model = _load_model()
    plans = model.build_automatic_slot_proposals(_three(), now=NOW)["proposals"]
    expected_charge = 45.0 + 0.1 * 0.92 / 7.1 * 100.0
    expected_discharge = 45.0 - 0.14 / 0.92 / 7.1 * 100.0
    assert abs(plans[0]["target_soc"] - expected_charge) < 0.001
    assert abs(plans[2]["target_soc"] - expected_discharge) < 0.001
    assert plans[0]["planned_energy_kwh"] == 0.1


def test_r6_mixed_safety_and_trade_charging_is_one_action():
    model = _load_model()
    rows = _rows()
    rows[0]["charge_from_grid_safety_kwh"] = 0.03
    rows[0]["charge_from_grid_trade_kwh"] = 0.04
    rows[1]["charge_from_grid_safety_kwh"] = 0.03
    rows[1]["charge_from_grid_trade_kwh"] = 0.04
    result = model.build_automatic_slot_proposals(_combined(rows), now=NOW)
    assert result["valid"] is True
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["purpose"] == "veiligheidsladen+handelsladen"
    assert result["proposals"][0]["planned_energy_kwh"] == 0.14


def test_r6_manual_overlap_splits_window_but_never_becomes_auto_proposal():
    model = _load_model()
    rows = _rows()
    for i in (0, 1, 2):
        rows[i]["charge_from_grid_trade_kwh"] = 0.06
    rows[1]["manual_slots"] = [2]
    rows[1]["manual_overlap_seconds"] = 450
    proposals = model.build_automatic_slot_proposals(_combined(rows), now=NOW)["proposals"]
    assert len(proposals) == 2
    assert [p["max_runtime_h"] for p in proposals] == [0.25, 0.25]
    assert all("2026-10-12T12:15:00" not in p["planner_identity"] for p in proposals)


def test_r6_pv_and_home_energy_never_become_explicit_control_actions():
    model = _load_model()
    result = model.build_automatic_slot_proposals(_combined(), now=NOW)
    assert result["valid"] is True
    assert result["proposals"] == []


def test_r6_rejects_broken_288_axis_and_unachievable_power_without_capping():
    model = _load_model()
    rows = _rows()[:-1]
    assert model.build_automatic_slot_proposals(_combined(rows), now=NOW)["valid"] is False
    rows = _rows()
    rows[1]["start"] = rows[0]["start"]
    assert model.build_automatic_slot_proposals(_combined(rows), now=NOW)["valid"] is False
    rows = _rows()
    rows[0]["charge_from_grid_trade_kwh"] = 2.0
    result = model.build_automatic_slot_proposals(_combined(rows), now=NOW)
    assert result["valid"] is True
    assert result["proposals"] == []
    assert any("automatic_power_above_configured_limit" in x for x in result["rejected"])


def test_r6_fails_closed_on_invalid_combined_and_on_forecast_missing():
    model = _load_model()
    source = _three()
    source["valid"] = False
    assert model.build_automatic_slot_proposals(source, now=NOW)["valid"] is False
    source = _three()
    source["native_slots"][5]["end"] = "wrong time"
    assert model.build_automatic_slot_proposals(source, now=NOW)["valid"] is False


def test_r6_module_has_no_own_hourly_policy_or_physical_execution():
    source = (INTEGRATION / "automatic_slot_bridge_model.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "automatic_slot_bridge.py").read_text(encoding="utf-8")
    assert "build_automatic_slot_proposals" in source
    assert "range(288)" not in source
    assert "physical_execution_enabled" in source
    assert "async_call(" not in source + runtime
    assert "third_party_control" not in source + runtime
    assert "DOEMSScheduler" not in source + runtime
    assert "async_sync_automatic_plans" in runtime
