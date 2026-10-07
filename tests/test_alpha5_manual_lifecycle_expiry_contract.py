from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load(name: str):
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    return importlib.import_module(f"custom_components.doems.{name}")


def _pending_plan(start: datetime, delay_min: float = 15) -> dict:
    return {
        "action": "laden",
        "execution_mode": "gepland",
        "start_time": start.isoformat(),
        "power_w": 1000,
        "target_soc": 80,
        "max_runtime_h": 2,
        "max_start_delay_min": delay_min,
        "lifecycle_status": "pending",
        "origin": "manual",
    }


def test_alpha5_before_window_end_is_not_expired() -> None:
    m = _load("manual_plan_lifecycle_model")
    start = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
    plan = _pending_plan(start)
    result = m.evaluate_manual_plan_expiry(
        plan,
        now=start + timedelta(minutes=14, seconds=59),
        slot=1,
    )
    assert result["status"] == "start_window_open"
    assert result["expired"] is False
    assert result["window_end"] == "2026-10-07T10:15:00+00:00"


def test_alpha5_exact_window_end_is_still_valid() -> None:
    m = _load("manual_plan_lifecycle_model")
    start = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
    result = m.evaluate_manual_plan_expiry(
        _pending_plan(start),
        now=start + timedelta(minutes=15),
        slot=1,
    )
    assert result["status"] == "start_window_open"
    assert result["expired"] is False


def test_alpha5_after_window_end_expires() -> None:
    m = _load("manual_plan_lifecycle_model")
    start = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
    result = m.evaluate_manual_plan_expiry(
        _pending_plan(start),
        now=start + timedelta(minutes=15, seconds=1),
        slot=1,
    )
    assert result["status"] == "expired"
    assert result["expired"] is True
    assert result["blockers"] == []


def test_alpha5_only_manual_pending_scheduled_is_applicable() -> None:
    m = _load("manual_plan_lifecycle_model")
    start = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
    now = start + timedelta(hours=1)

    for lifecycle in ("concept", "actief", "voltooid", "geannuleerd", "fout", "verlopen"):
        plan = _pending_plan(start)
        plan["lifecycle_status"] = lifecycle
        result = m.evaluate_manual_plan_expiry(plan, now=now, slot=1)
        assert result["applicable"] is False
        assert result["expired"] is False

    plan = _pending_plan(start)
    plan["origin"] = "automatic_72h_planner"
    result = m.evaluate_manual_plan_expiry(plan, now=now, slot=1)
    assert result["applicable"] is False

    plan = _pending_plan(start)
    plan["execution_mode"] = "direct"
    result = m.evaluate_manual_plan_expiry(plan, now=now, slot=1)
    assert result["status"] == "blocked"
    assert "manual_plan_1_execution_mode_invalid" in result["blockers"]


def test_alpha5_invalid_pending_plan_blocks_fail_closed() -> None:
    m = _load("manual_plan_lifecycle_model")
    now = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)
    plan = _pending_plan(now - timedelta(hours=1))
    plan["start_time"] = "not-a-date"
    plan["max_start_delay_min"] = 0

    result = m.evaluate_manual_plan_expiry(plan, now=now, slot=2)
    assert result["status"] == "blocked"
    assert result["expired"] is False
    assert "manual_plan_2_start_time_invalid" in result["blockers"]
    assert "manual_plan_2_start_delay_invalid" in result["blockers"]


def test_alpha5_next_deadline_selects_earliest_pending_slot() -> None:
    m = _load("manual_plan_lifecycle_model")
    now = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    plans = [
        _pending_plan(datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc), 15),
        _pending_plan(datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc), 30),
        _pending_plan(datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc), 15),
    ]
    result = m.next_manual_expiry_deadline(plans, now=now)
    assert result["slot"] == 2
    assert result["deadline"] == datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc)


def test_alpha5_store_release_is_atomic_reusable_and_audited_by_contract() -> None:
    store = (INTEGRATION / "manual_plan_store.py").read_text(encoding="utf-8")
    projection = (INTEGRATION / "manual_soc_projection_model.py").read_text(encoding="utf-8")

    assert "async_release_expired_manual_plans" in store
    assert '"status": "verlopen"' in store
    assert '"reason": MANUAL_EXPIRY_REASON' in store
    assert 'cleared = new_manual_plan()' in store
    assert '"terminal_events": deepcopy(' in store
    assert "self._notify()" in store

    # Once the active slot is cleared, R3 no longer sees it as a commitment.
    assert '_ACTIVE_MANUAL_LIFECYCLES = {"pending", "actief"}' in projection


def test_alpha5_runtime_is_timer_only_and_has_no_execution_authority() -> None:
    runtime = (INTEGRATION / "manual_plan_lifecycle.py").read_text(encoding="utf-8")
    init = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")

    assert "DOEMSManualPlanLifecycle" in init
    assert "async_track_point_in_utc_time" in runtime
    assert "doems_manual_plan_lifecycle" in sensor
    assert '"physical_execution_authority": False' in runtime
    assert '"scheduler_active": False' in runtime
    assert '"automatic_planner_active": False' in runtime

    assert "async_call(" not in runtime
    assert "third_party_control" not in runtime
    assert "DOEMSScheduler" not in runtime
    assert "automatic_72h_planner" not in runtime
