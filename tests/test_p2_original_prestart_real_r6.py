"""Behavioral proof: actual DOEMS R6 proposal through frozen Alpha84 Pre-start.

The original Alpha84 class is executed unchanged; synthetic telemetry is
used only for isolated software regression, never as live approval.
"""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from custom_components.doems.automatic_slot_bridge_model import build_automatic_slot_proposals

SOURCE = Path(__file__).resolve().parents[1] / "reference/anker_ems_alpha84/prestart_validator.py"
NOW = datetime(2026, 10, 27, 11, 55, tzinfo=timezone.utc)


def original_validator():
    tree = ast.parse(SOURCE.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "AnkerEmsPreStartValidator")
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    util = SimpleNamespace(
        utcnow=lambda: NOW,
        parse_datetime=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
        DEFAULT_TIME_ZONE=timezone.utc, UTC=timezone.utc,
    )
    ns = {"Any": Any, "datetime": datetime, "deepcopy": __import__("copy").deepcopy,
          "dt_util": util, "MIN_SOC_PERCENT": 5, "MAX_SOC_PERCENT": 100}
    exec(compile(module, str(SOURCE), "exec"), ns)
    return ns["AnkerEmsPreStartValidator"]()


def real_proposal():
    start = NOW.replace(minute=0) + timedelta(hours=1)
    rows = []
    for i in range(288):
        st = start + timedelta(minutes=15 * i)
        rows.append({
            "index": i, "start": st.isoformat(),
            "end": (st + timedelta(minutes=15)).isoformat(),
            "start_soc_percent": 40.0,
            "charge_from_grid_trade_kwh": 0.125 if i == 0 else 0.0,
            "price_source": "known",
        })
    combined = {
        "status": "ready", "valid": True,
        "native_slot_count": 288, "native_slots": rows,
        "capacity_kwh": 7.1, "charge_efficiency_percent": 95,
        "discharge_efficiency_percent": 95,
        "max_charge_power_w": 800, "max_discharge_power_w": 800,
    }
    result = build_automatic_slot_proposals(combined, now=NOW)
    assert result["valid"] and len(result["proposals"]) == 1
    return result["proposals"][0]


def inputs():
    proposal = real_proposal()
    return {
        "scheduler_ready": True, "scheduler_selected_slot": 1,
        "scheduler_slots": {1: {**proposal, "lifecycle_status": "pending"}},
        "auto_bridge_candidates": [proposal], "auto_bridge_slot_preview": [],
        "auto_plan_72h_valid": True, "forecast_ready": True,
        "auto_plan_72h_execution_buffer_safe": True,
        "auto_bridge_valid": True, "auto_bridge_invalid_candidate_count": 0,
        "soc": 40, "max_charge_power_w": 800, "max_discharge_power_w": 800,
    }


def test_original_prestart_accepts_real_doems_r6_candidate_as_input():
    data = inputs()
    result = original_validator().evaluate(data)
    assert result["auto_prestart_required"] is True
    assert result["auto_prestart_safe"] is True
    assert result["auto_prestart_current_identity_match"] is True
    assert result["auto_prestart_current_signature_match"] is True
    assert result["auto_prestart_execution_enabled"] is False


def test_original_prestart_blocks_missing_doems_candidate():
    data = inputs()
    data["auto_bridge_candidates"] = []
    result = original_validator().evaluate(data)
    assert result["auto_prestart_safe"] is False
    assert "planner_identity_missing" in result["auto_prestart_reasons"]


def test_original_prestart_blocks_invalid_forecast():
    data = inputs()
    data["forecast_ready"] = False
    result = original_validator().evaluate(data)
    assert result["auto_prestart_safe"] is False
    assert "forecast_not_ready" in result["auto_prestart_reasons"]
