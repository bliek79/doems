"""Partial timeout evidence and numerical parity of optional measurements."""
from __future__ import annotations

import asyncio
import sys

import pytest

from test_alpha7_1_planner_migration_contract import _axis, _prices, _load
from test_r5_manager_sequential_async import _load_manager, _make_instance, _until_idle


def test_diagnostics_do_not_change_native_planner_output():
    model = _load("automatic_combined_planner_model")
    trace_type = _load("planner_diagnostics").PlannerDiagnostics
    energy, solar = _axis(home_kwh=0.10, solar_kwh=0.02)
    kwargs = dict(energy_slots=energy, solar_slots=solar, plans=[],
                  start_soc_percent=26, capacity_kwh=7.1,
                  price_by_start=_prices(energy), stage="automatic")
    original = model.build_planner_bundle(**kwargs)
    trace = trace_type("automatic", 1)
    trace.start()
    measured = model.build_planner_bundle(**kwargs, diagnostics=trace)
    trace.finish("completed")
    assert measured == original
    result = trace.snapshot()
    assert result["counts"]["simulation_count"] == original["automatic"]["planner_simulation_count"]
    assert result["counts"]["safety_trials"] > 0
    assert result["phase_seconds"]["safety_charging"] >= 0
    assert result["phase_seconds"]["economic_home_planning"] >= 0
    assert result["worker_cpu_seconds"] >= 0


def test_timeout_retains_partial_model_phase_and_counts():
    model = _load("automatic_combined_planner_model")
    trace = _load("planner_diagnostics").PlannerDiagnostics("automatic", 4)
    energy, solar = _axis(home_kwh=0.10)
    trace.start()
    def guard():
        if trace.counts.get("safety_trials", 0):
            raise model.PlannerComputeBudgetExceeded("planner_compute_budget_exceeded")
    with pytest.raises(model.PlannerComputeBudgetExceeded):
        model.build_planner_bundle(energy_slots=energy, solar_slots=solar,
            plans=[], start_soc_percent=26, capacity_kwh=7.1,
            price_by_start=_prices(energy), stage="automatic",
            diagnostics=trace, check_work=guard)
    trace.finish("budget_exceeded")
    result = trace.snapshot()
    assert result["last_phase"] == "safety_charging"
    assert result["counts"]["safety_trials"] == 1
    assert result["phase_seconds"]["safety_charging"] >= 0
    assert result["result"] == "budget_exceeded"


def test_manager_publishes_current_duration_and_partial_evidence(monkeypatch):
    def compute(**kwargs):
        diagnostics = kwargs["diagnostics"]
        diagnostics.enter("safety_charging")
        diagnostics.count("safety_trials")
        exc = sys.modules["custom_components.doems.automatic_combined_planner_model"].PlannerComputeBudgetExceeded
        raise exc("planner_compute_budget_exceeded")
    cls = _load_manager(monkeypatch, compute)
    async def run():
        manager = _make_instance(cls)
        manager._automatic_last_compute_seconds = 999.0
        await manager.async_request_refresh("quarter_boundary")
        await _until_idle(manager)
        snapshot = manager.snapshot("automatic")
        result = snapshot["planner_automatic_diagnostics"]
        assert snapshot["blockers"] == ["planner_compute_budget_exceeded"]
        assert snapshot["planner_automatic_last_compute_seconds"] < 999.0
        assert result["manager_elapsed_seconds"] == snapshot["planner_automatic_last_compute_seconds"]
        assert result["result"] == "budget_exceeded"
        assert result["last_phase"] == "safety_charging"
        assert result["counts"]["safety_trials"] == 1
        assert manager._combined_compute_count == 0
        assert snapshot["physical_execution_enabled"] is False
    asyncio.run(run())
