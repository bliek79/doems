"""P0 regression: native Combined slots must fail closed before actuation."""
from datetime import datetime, timedelta, timezone

from custom_components.doems.combined_execution_shadow import evaluate_combined_execution_shadow


def _snapshot():
    start = datetime(2026, 10, 23, tzinfo=timezone.utc)
    slots = []
    for index in range(288):
        a = start + timedelta(minutes=15 * index)
        b = a + timedelta(minutes=15)
        slots.append({
            "start": a.isoformat(), "end": b.isoformat(),
            "manual_charge_kwh": 0, "manual_discharge_kwh": 0,
            "charge_from_grid_safety_kwh": 0,
            "charge_from_grid_trade_kwh": 0,
            "discharge_to_grid_kwh": 0,
        })
    return {"valid": True, "blockers": [], "native_slots": slots}


def test_normal_combined_slot_is_ready_without_authority():
    snapshot = _snapshot()
    snapshot["native_slots"][0]["manual_charge_kwh"] = 0.5
    result = evaluate_combined_execution_shadow(
        snapshot, now=datetime(2026, 10, 23, 0, 1, tzinfo=timezone.utc))
    assert result["status"] == "shadow_ready"
    assert result["planned_power_w"] == 2000
    assert result["physical_execution_enabled"] is False


def test_reject_gap_even_outside_current_quarter():
    snapshot = _snapshot()
    slot = snapshot["native_slots"][10]
    slot["start"] = (datetime.fromisoformat(slot["start"]) + timedelta(minutes=15)).isoformat()
    slot["end"] = (datetime.fromisoformat(slot["end"]) + timedelta(minutes=15)).isoformat()
    result = evaluate_combined_execution_shadow(
        snapshot, now=datetime(2026, 10, 23, 0, 1, tzinfo=timezone.utc))
    assert result["reason"] == "non_contiguous_quarters"


def test_reject_power_above_static_adapter_limit():
    snapshot = _snapshot()
    snapshot["native_slots"][0]["manual_charge_kwh"] = 1.0
    result = evaluate_combined_execution_shadow(
        snapshot, now=datetime(2026, 10, 23, 0, 1, tzinfo=timezone.utc))
    assert result["reason"] == "power_out_of_range"


def test_idle_is_observable_not_an_execution():
    result = evaluate_combined_execution_shadow(
        _snapshot(), now=datetime(2026, 10, 23, 0, 1, tzinfo=timezone.utc))
    assert result["status"] == "shadow_ready"
    assert result["action"] == "idle"
    assert result["execution_performed"] is False
