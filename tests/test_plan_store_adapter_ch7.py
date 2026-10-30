"""Chapter 7 conservative manual slot adapter contract tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "custom_components" / "doems" / "plan_store_adapter.py"
SPEC = importlib.util.spec_from_file_location("doems_ch7_adapter_test", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Store:
    def __init__(self, plans):
        self.plans = plans

    def get_plan(self, slot):
        return self.plans.get(slot, {})


def planned(**changes):
    data = {
        "origin": "manual",
        "execution_mode": "gepland",
        "action": "laden",
        "lifecycle_status": "concept",
        "start_time": "2026-11-01T12:00:00+01:00",
        "power_w": 1000,
        "target_soc": 80,
        "max_runtime_h": 1,
    }
    data.update(changes)
    return data


def test_scheduled_manual_concept_constrains_soc_projection():
    result = MODULE.manual_constraints(Store({1: planned()}))
    assert len(result) == 1
    assert result[0]["id"] == "slot_1"
    assert result[0]["action"] == "charge"
    assert result[0]["start_time"] == "2026-11-01T11:00:00+00:00"
    assert result[0]["lifecycle_status"] == "pending"


def test_automatic_and_active_slots_are_not_silently_recast_manual():
    result = MODULE.manual_constraints(Store({
        1: planned(origin="automatic_72h_planner"),
        2: planned(lifecycle_status="voltooid"),
        3: planned(execution_mode="direct"),
    }))
    assert result == []


def test_manual_discharge_pending_is_preserved():
    result = MODULE.manual_constraints(Store({2: planned(
        action="ontladen", lifecycle_status="pending", target_soc=30
    )}))
    assert result[0]["action"] == "discharge"
    assert result[0]["target_soc"] == 30.0


def test_invalid_naive_date_fails_closed():
    import pytest
    with pytest.raises(ValueError, match="invalid_manual_slot_1"):
        MODULE.manual_constraints(Store({
            1: planned(start_time="2026-11-01T12:00:00")
        }))


def test_invalid_power_fails_closed():
    import pytest
    with pytest.raises(ValueError, match="invalid_manual_slot_1"):
        MODULE.manual_constraints(Store({1: planned(power_w=0)}))


def test_active_automatic_retains_origin_preparation_end_and_command_target():
    from datetime import datetime, timezone
    result = MODULE.manual_constraints(Store({1: planned(
        origin='automatic_72h_planner', lifecycle_status='actief', purpose='safety_charge',
        power_start_time='2026-11-01T11:02:00+00:00', planned_end_time='2026-11-01T11:15:00+00:00',
        command_target_soc=90, target_soc=75)}), now=datetime(2026,11,1,11,5,tzinfo=timezone.utc))
    assert result[0]['origin'] == 'safety'
    assert result[0]['target_soc'] == 90
    assert result[0]['max_runtime_h'] == .25
    assert result[0]['power_start_time'] == '2026-11-01T11:02:00+00:00'
    assert result[0]['lifecycle_status'] == 'active'


def test_future_revisable_automatic_does_not_double_count_generated_route():
    from datetime import datetime, timezone
    result = MODULE.manual_constraints(Store({1: planned(
        origin='automatic_72h_planner', lifecycle_status='pending')}),
        now=datetime(2026,10,30,12,tzinfo=timezone.utc))
    assert result == []
