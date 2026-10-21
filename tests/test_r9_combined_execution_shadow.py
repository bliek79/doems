"""R9 Combined shadow contract tests; no Home Assistant runtime required."""
from datetime import datetime, timedelta, timezone

from custom_components.doems.combined_execution_shadow import evaluate_combined_execution_shadow


def _snapshot():
    start = datetime(2026, 10, 21, tzinfo=timezone.utc)
    return {
        "valid": True, "blockers": [],
        "native_slots": [
            {"start": (start + timedelta(minutes=15 * i)).isoformat(),
             "end": (start + timedelta(minutes=15 * (i + 1))).isoformat(),
             "manual_charge_kwh": 0, "manual_discharge_kwh": 0,
             "charge_from_grid_safety_kwh": 0,
             "charge_from_grid_trade_kwh": 0,
             "discharge_to_grid_kwh": 0}
            for i in range(288)
        ],
    }


def test_current_quarter_is_observed_without_execution():
    snapshot = _snapshot()
    snapshot["native_slots"][2]["manual_charge_kwh"] = 0.625
    result = evaluate_combined_execution_shadow(
        snapshot, now=datetime(2026, 10, 21, 0, 31, tzinfo=timezone.utc)
    )
    assert result["status"] == "shadow_ready"
    assert result["slot"] == 2
    assert result["planned_power_w"] == 2500
    assert result["physical_execution_enabled"] is False
    assert result["execution_performed"] is False


def test_reject_invalid_planner():
    snapshot = _snapshot()
    snapshot["valid"] = False
    assert evaluate_combined_execution_shadow(
        snapshot, now=datetime(2026, 10, 21, tzinfo=timezone.utc)
    )["status"] == "blocked"


def test_reject_conflicting_directions():
    snapshot = _snapshot()
    snapshot["native_slots"][0]["manual_charge_kwh"] = 0.5
    snapshot["native_slots"][0]["discharge_to_grid_kwh"] = 0.1
    assert evaluate_combined_execution_shadow(
        snapshot, now=datetime(2026, 10, 21, tzinfo=timezone.utc)
    )["reason"] == "conflicting_directions"


def test_reject_non_native_length():
    snapshot = _snapshot()
    snapshot["native_slots"].pop()
    assert evaluate_combined_execution_shadow(
        snapshot, now=datetime(2026, 10, 21, tzinfo=timezone.utc)
    )["reason"] == "native_288_required"
