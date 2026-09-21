from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"
ALPHA = INTEGRATION / "ems_alpha76"


def _install_homeassistant_dt_stub() -> None:
    if "homeassistant.util.dt" in sys.modules:
        return
    homeassistant = types.ModuleType("homeassistant")
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")
    dt.UTC = timezone.utc
    dt.DEFAULT_TIME_ZONE = timezone.utc
    dt.utcnow = lambda: datetime.now(timezone.utc)
    dt.now = lambda: datetime.now(timezone.utc)
    dt.parse_datetime = lambda value: datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    util.dt = dt
    homeassistant.util = util
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = dt


def _load_bridge():
    _install_homeassistant_dt_stub()
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    if "custom_components.doems.ems_alpha76" not in sys.modules:
        package = types.ModuleType("custom_components.doems.ems_alpha76")
        package.__path__ = [str(ALPHA)]
        sys.modules["custom_components.doems.ems_alpha76"] = package
    return importlib.import_module("custom_components.doems.ems_alpha76.planner_action_bridge")


def _row(time: str, *, safety_kwh: float = 1.0) -> dict:
    return {
        "time": time,
        "charge_from_grid_safety_kwh": safety_kwh,
        "charge_from_grid_trade_kwh": 0.0,
        "discharge_to_grid_kwh": 0.0,
        "soc_start": 40.0,
        "execution_reserve_floor_start_soc": 12.0,
        "execution_reserve_floor_soc": 12.0,
        "price": 0.20,
        "price_source": "known",
    }


def _base_data(existing: dict | None = None, *, row_time: str = "2026-09-21T11:15:00+00:00") -> dict:
    slots = {
        1: existing or {
            "action": "geen",
            "status": "leeg",
            "lifecycle_status": "concept",
            "origin": "manual",
        },
        2: {
            "action": "geen",
            "status": "leeg",
            "lifecycle_status": "concept",
            "origin": "manual",
        },
        3: {
            "action": "geen",
            "status": "leeg",
            "lifecycle_status": "concept",
            "origin": "manual",
        },
    }
    return {
        "auto_plan_72h_plan": [_row(row_time)],
        "auto_plan_72h_valid": True,
        "auto_plan_72h_execution_buffer_safe": False,
        "forecast_ready": True,
        "max_charge_power_w": 3200,
        "max_discharge_power_w": 3200,
        "battery_capacity_kwh": 7.2,
        "charge_efficiency_percent": 92.0,
        "discharge_efficiency_percent": 92.0,
        "scheduler_slots": slots,
    }


def _pending_existing(
    *,
    start: str = "2026-09-21T11:00:00+00:00",
    end: str = "2026-09-21T12:00:00+00:00",
    action: str = "laden",
    purpose: str = "veiligheidsladen",
) -> dict:
    return {
        "action": action,
        "purpose": purpose,
        "status": "wachtend",
        "lifecycle_status": "pending",
        "origin": "automatic_72h_planner",
        "start_time": start,
        "planned_end_time": end,
        "max_start_delay_min": 10,
        "planner_identity": "stable-existing-identity",
        "planner_signature": "laden|veiligheidsladen|2026-09-21T11:00:00+00:00|2026-09-21T12:00:00+00:00|50.0|1.0",
    }


def test_one_quarter_roll_preserves_pending_identity() -> None:
    bridge = _load_bridge()
    result = bridge.build_planner_action_bridge(
        _base_data(_pending_existing()),
        now=datetime(2026, 9, 21, 11, 8, tzinfo=timezone.utc),
    )
    proposal = result["auto_bridge_slot_preview"][0]
    assert proposal["suggested_slot"] == 1
    assert proposal["automatic_pending_match"] is True
    assert proposal["quarter_roll_identity_continuity"] is True
    assert proposal["planner_identity"] == "stable-existing-identity"
    assert proposal["planner_signature"] != _pending_existing()["planner_signature"]


def test_more_than_one_quarter_does_not_inherit_identity() -> None:
    bridge = _load_bridge()
    result = bridge.build_planner_action_bridge(
        _base_data(_pending_existing(), row_time="2026-09-21T11:30:00+00:00"),
        now=datetime(2026, 9, 21, 11, 8, tzinfo=timezone.utc),
    )
    proposal = result["auto_bridge_slot_preview"][0]
    assert proposal["quarter_roll_identity_continuity"] is False
    assert proposal["planner_identity"] != "stable-existing-identity"


def test_different_action_or_purpose_does_not_inherit_identity() -> None:
    bridge = _load_bridge()
    for existing in (
        _pending_existing(action="ontladen"),
        _pending_existing(purpose="handelsladen"),
    ):
        result = bridge.build_planner_action_bridge(
            _base_data(existing),
            now=datetime(2026, 9, 21, 11, 8, tzinfo=timezone.utc),
        )
        proposal = result["auto_bridge_slot_preview"][0]
        assert proposal["quarter_roll_identity_continuity"] is False
        assert proposal["planner_identity"] != "stable-existing-identity"


def test_non_overlapping_window_does_not_inherit_identity() -> None:
    bridge = _load_bridge()
    existing = _pending_existing(end="2026-09-21T11:10:00+00:00")
    result = bridge.build_planner_action_bridge(
        _base_data(existing),
        now=datetime(2026, 9, 21, 11, 8, tzinfo=timezone.utc),
    )
    proposal = result["auto_bridge_slot_preview"][0]
    assert proposal["quarter_roll_identity_continuity"] is False
    assert proposal["planner_identity"] != "stable-existing-identity"


def test_expired_original_start_window_does_not_inherit_identity() -> None:
    bridge = _load_bridge()
    result = bridge.build_planner_action_bridge(
        _base_data(_pending_existing()),
        now=datetime(2026, 9, 21, 11, 11, tzinfo=timezone.utc),
    )
    proposal = result["auto_bridge_slot_preview"][0]
    assert proposal["quarter_roll_identity_continuity"] is False
    assert proposal["planner_identity"] != "stable-existing-identity"


def test_physical_control_boundary_remains_closed() -> None:
    bridge_text = (ALPHA / "planner_action_bridge.py").read_text(encoding="utf-8")
    runtime_text = (INTEGRATION / "ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in bridge_text
    assert '"physical_execution_authority": False' in runtime_text
    assert '"automatic_execution_armed": False' in runtime_text
