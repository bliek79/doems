"""Targeted R5 runtime/performance gate; keep R0-R4 byte-identical."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Event
from time import perf_counter

import pytest

from test_alpha7_1_planner_migration_contract import (
    _axis, _load, _plan, _prices,
)


def _run(energy, solar, prices, *, soc=50.0, plans=()):
    return _load("automatic_combined_planner_model").build_planner_bundle(
        energy_slots=energy,
        solar_slots=solar,
        price_by_start=prices,
        plans=list(plans),
        start_soc_percent=soc,
        capacity_kwh=7.1,
    )


def test_guard_rejects_superseded_and_over_budget_worker():
    model = _load("automatic_combined_planner_model")
    runtime = _load("automatic_combined_planner_runtime")
    stop = Event()
    check = runtime.make_planner_work_guard(stop, seconds=20)
    check()
    stop.set()
    with pytest.raises(model.PlannerComputeCancelled):
        check()
    with pytest.raises(model.PlannerComputeBudgetExceeded):
        runtime.make_planner_work_guard(Event(), seconds=0)()


def test_native_model_checks_cooperative_cancellation_inside_full_route():
    model = _load("automatic_combined_planner_model")
    energy, solar = _axis(home_kwh=0.1)
    prices = _prices(energy)
    calls = 0

    def interrupt():
        nonlocal calls
        calls += 1
        if calls == 5:
            raise model.PlannerComputeCancelled("test_superseded")

    with pytest.raises(model.PlannerComputeCancelled):
        model.build_planner_bundle(
            energy_slots=energy, solar_slots=solar, plans=[],
            start_soc_percent=50, capacity_kwh=7.1,
            price_by_start=prices, check_work=interrupt,
        )
    assert calls == 5


def test_no_grid_charge_if_solar_avoids_future_grid_need():
    energy, solar = _axis(home_kwh=0.04, solar_kwh=0.15)
    result = _run(energy, solar, _prices(energy, import_price=0.22, export_price=0.07), soc=40)
    for key in ("automatic", "combined"):
        planner = result[key]
        assert planner["native_slot_count"] == 288
        assert sum(row["charge_from_grid_kwh"] for row in planner["native_slots"]) == 0
        assert planner["hard_safety_floor_soc"] == 10
        assert planner["physical_execution_enabled"] is False


def test_economic_precharge_for_later_expensive_home_need():
    energy, solar = _axis(home_kwh=0.14)
    for i in range(8):
        energy[i]["home_kwh"] = 0
    prices = _prices(energy, import_price=0.55, export_price=0.03)
    for i in range(8):
        prices[energy[i]["start"]]["import_all_in"] = 0.06
    result = _run(energy, solar, prices, soc=10)
    automatic, combined = result["automatic"], result["combined"]
    assert automatic["native_slot_count"] == 288
    assert automatic["dynamic_reserve_max_soc_percent"] == 10
    assert sum(row["charge_from_grid_kwh"] for row in automatic["native_slots"][:8]) > 0
    assert automatic["native_slots"] == combined["native_slots"]
    assert automatic["planner_economic_trial_count"] <= 576
    assert automatic["physical_execution_enabled"] is False


def test_three_manual_commitments_are_hard_only_in_combined():
    energy, solar = _axis(home_kwh=0.07, solar_kwh=0.01)
    start = datetime(2026, 10, 7, tzinfo=timezone.utc)
    plans = [
        _plan(action="laden", start=start + timedelta(hours=2),
              target_soc=70, runtime_h=1, slot=1),
        _plan(action="ontladen", start=start + timedelta(hours=6),
              target_soc=35, runtime_h=1, slot=2),
        _plan(action="laden", start=start + timedelta(hours=10),
              target_soc=65, runtime_h=1, slot=3),
    ]
    result = _run(energy, solar, _prices(energy), soc=55, plans=plans)
    automatic, combined = result["automatic"], result["combined"]
    assert automatic["native_slot_count"] == combined["native_slot_count"] == 288
    assert automatic["manual_commitment_count"] == 0
    assert combined["manual_commitment_slots"] == [1, 2, 3]
    assert automatic["native_slots"][8]["manual_slots"] == []
    for index, slot in ((8, 1), (24, 2), (40, 3)):
        assert combined["native_slots"][index]["manual_slots"] == [slot]
        assert combined["native_slots"][index]["manual_overlap_seconds"] == 900
    assert combined["execution_enabled"] is False


def test_stress_288_quarters_has_bounded_trial_count_and_runtime():
    energy, solar = _axis(home_kwh=0.14)
    for i in range(288):
        energy[i]["home_kwh"] = 0.04 + (i % 8) * 0.023
        solar[i]["solar_kwh"] = max(0.0, 0.19 - abs((i % 96) - 48) / 240)
    prices = _prices(energy, import_price=0.35, export_price=0.08)
    for i in range(288):
        prices[energy[i]["start"]]["import_all_in"] = (
            0.08 if i % 24 < 6 else (0.52 if i % 24 >= 14 else 0.28)
        )
    start = perf_counter()
    result = _run(energy, solar, prices, soc=35)
    elapsed = perf_counter() - start
    assert result["valid"] is True
    for kind in ("automatic", "combined"):
        planner = result[kind]
        assert planner["native_slot_count"] == 288
        assert planner["planner_economic_trial_count"] <= 576
        assert planner["planner_simulation_count"] <= 1200
    # CI threshold is deliberately generous; the live worker uses a separate,
    # enforceable cooperative 20-second budget on the user's device.
    assert elapsed < 18, f"288-slot dual-planner stress took {elapsed:.2f}s"


def test_worker_recovery_contract_keeps_latest_request_and_cache_atomic():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1]
              / "custom_components/doems/automatic_combined_planner.py").read_text()
    assert 'self._active_cancel_event.set()' in source
    assert 'self._active_generation == self._generation' in source
    assert 'self._cached_bundle.get("status") == "ready"' in source
    assert 'except PlannerComputeBudgetExceeded as err:' in source
    assert 'except PlannerComputeCancelled:' in source
    assert 'self._pending_request = request' in source
    assert 'await self.hass.async_add_executor_job(compute)' in source
    assert 'self._cached_bundle = bundle' in source
