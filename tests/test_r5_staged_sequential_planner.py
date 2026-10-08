"""R5.1.5: staged Automatic -> Combined sequencing contract."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from test_alpha7_1_planner_migration_contract import _axis, _load, _plan, _prices


def _stage(*, manual=(), soc=55, home=0.045, solar=0.0):
    model = _load("automatic_combined_planner_model")
    energy, solar_slots = _axis(home_kwh=home, solar_kwh=solar)
    kwargs = dict(
        energy_slots=energy, solar_slots=solar_slots,
        price_by_start=_prices(energy, import_price=0.23, export_price=0.05),
        capacity_kwh=7.1, start_soc_percent=soc,
    )
    first = model.build_planner_bundle(
        **kwargs, plans=[], stage="automatic",
    )
    assert first["automatic"]["native_slot_count"] == 288
    second = model.build_planner_bundle(
        **kwargs, plans=list(manual), stage="combined",
        automatic_snapshot=first["automatic"],
    )
    return first, second


def test_automatic_can_finish_before_combined_without_extra_automatic_compute():
    model = _load("automatic_combined_planner_model")
    first, second = _stage()
    assert first["valid"]
    assert first["automatic"]["valid"]
    assert first["combined"] == {}
    assert second["valid"]
    assert second["automatic"]["native_slots"] == first["automatic"]["native_slots"]
    assert second["combined"]["mode"] == "combined_planner"
    assert second["combined"]["native_slots"] == first["automatic"]["native_slots"]
    assert (
        second["combined"]["planner_simulation_count"]
        == first["automatic"]["planner_simulation_count"]
    )


def test_manual_plan_changes_only_combined_and_never_automatic():
    start = datetime(2026, 10, 7, tzinfo=timezone.utc)
    manual = [
        _plan(action="laden", start=start + timedelta(hours=1),
              target_soc=72, runtime_h=1, slot=1, power_w=1000),
        _plan(action="ontladen", start=start + timedelta(hours=4),
              target_soc=35, runtime_h=1, slot=2, power_w=500),
        _plan(action="laden", start=start + timedelta(hours=6),
              target_soc=65, runtime_h=1, slot=3, power_w=800),
    ]
    automatic, combined = _stage(manual=manual, soc=50)
    assert combined["automatic"]["native_slots"] == automatic["automatic"]["native_slots"]
    assert combined["combined"]["manual_commitment_slots"] == [1, 2, 3]
    assert [combined["combined"]["native_slots"][i]["manual_slots"]
            for i in [4, 16, 24]] == [[1], [2], [3]]
    assert all(x["manual_slots"] == [] for x in automatic["automatic"]["native_slots"])
    assert combined["combined"]["physical_execution_enabled"] is False


def test_combined_requires_completed_automatic():
    model = _load("automatic_combined_planner_model")
    energy, solar = _axis()
    with pytest.raises(ValueError, match="automatic_stage_required"):
        model.build_planner_bundle(
            energy_slots=energy, solar_slots=solar, plans=[],
            start_soc_percent=50, capacity_kwh=7.1,
            price_by_start=_prices(energy), stage="combined",
        )


def test_quarter_trigger_and_manual_event_stage_routing_are_separate():
    root = Path(__file__).resolve().parents[1] / "custom_components/doems"
    energy = (root / "energy_coordinator.py").read_text()
    manager = (root / "automatic_combined_planner.py").read_text()
    runtime = (root / "automatic_combined_planner_runtime.py").read_text()
    assert "minute=[0, 15, 30, 45]" in energy
    assert 'if reason == "manual_plan_changed":' in manager
    assert "self.async_request_manual_refresh(reason)" in manager
    assert 'self._enqueue_combined("automatic_completed")' in manager
    assert "self._manual_plans_snapshot()" in manager
    assert "prebuilt_energy_slots" in runtime
    assert 'stage="automatic"' in manager
    assert '"stage": "combined"' in manager
    assert "make_planner_work_guard(stop)" in manager
    assert "await self.hass.async_add_executor_job(compute)" in manager
