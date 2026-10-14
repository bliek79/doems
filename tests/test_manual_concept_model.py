"""Manual concept expiry model: 15-minute window, ownership and incomplete drafts."""
from datetime import datetime, timedelta, timezone
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
import pytest

MODEL = Path(__file__).resolve().parents[1] / "custom_components/doems/manual_plan_lifecycle_model.py"
spec = spec_from_file_location("manual_expiry_model", MODEL)
model = module_from_spec(spec)
spec.loader.exec_module(model)
T = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)


def draft(*, lifecycle="concept", origin="manual", action="laden",
          mode="gepland", start=T, delay=10):
    return {
        "origin": origin, "lifecycle_status": lifecycle, "action": action,
        "execution_mode": mode,
        "start_time": start.isoformat() if isinstance(start, datetime) else start,
        "max_start_delay_min": delay,
        "power_w": 3000, "target_soc": 80, "max_runtime_h": 1.25,
    }


@pytest.mark.parametrize("delta_minutes,expired", [
    (-1, False), (0, False), (9, False), (10, False),
    (10.0001, True), (100, True),
])
def test_manual_concept_exact_start_window(delta_minutes, expired):
    result = model.evaluate_manual_plan_expiry(
        draft(), now=T + timedelta(minutes=delta_minutes), slot=2
    )
    assert result["applicable"] is True
    assert result["expired"] is expired
    assert result["window_end"] == (T + timedelta(minutes=10)).isoformat()


@pytest.mark.parametrize("lifecycle", ["pending", "concept"])
def test_pending_and_concept_expire_at_same_boundary(lifecycle):
    result = model.evaluate_manual_plan_expiry(
        draft(lifecycle=lifecycle), now=T + timedelta(minutes=11)
    )
    assert result["expired"] is True


@pytest.mark.parametrize("changes", [
    {"action": "geen"}, {"start": None}, {"mode": "direct"},
    {"origin": "automatic_72h_planner"}, {"lifecycle": "actief"},
    {"lifecycle": "voltooid"}, {"lifecycle": "geannuleerd"},
])
def test_non_applicable_or_incomplete_concept_is_preserved(changes):
    result = model.evaluate_manual_plan_expiry(
        draft(**changes), now=T + timedelta(days=3)
    )
    assert result["applicable"] is False
    assert result["expired"] is False


@pytest.mark.parametrize("changes", [
    {"start": "nonsense"}, {"start": "2026-10-14T15:00:00"},
    {"delay": 0}, {"delay": 180}, {"delay": "incorrect"},
])
def test_bad_concept_is_fail_closed_not_discarded(changes):
    result = model.evaluate_manual_plan_expiry(
        draft(**changes), now=T + timedelta(days=3), slot=2
    )
    assert result["applicable"] is True
    assert result["expired"] is False
    assert result["status"] == "blocked"
    assert result["blockers"]


def test_old_pending_invalid_remains_blocked():
    result = model.evaluate_manual_plan_expiry(
        draft(lifecycle="pending", action="geen"),
        now=T + timedelta(days=1), slot=3,
    )
    assert "manual_plan_3_action_invalid" in result["blockers"]
    assert not result["expired"]


def test_next_timer_includes_concept_but_skips_incomplete_and_auto():
    entries = [
        draft(start=None),
        draft(start=T + timedelta(hours=1)),
        draft(lifecycle="pending", start=T + timedelta(hours=2)),
    ]
    result = model.next_manual_expiry_deadline(entries, now=T)
    assert result["slot"] == 2
    assert result["deadline"] == T + timedelta(hours=1, minutes=10)


def test_old_slot_is_due_at_startup():
    result = model.evaluate_manual_plan_expiry(
        draft(start=T - timedelta(days=2)), now=T
    )
    assert result["expired"] is True


def test_idempotent_model_never_mutates_user_plan():
    original = draft(start=T - timedelta(days=2))
    before = original.copy()
    for _ in range(4):
        assert model.evaluate_manual_plan_expiry(original, now=T)["expired"]
    assert original == before


def test_aware_clock_required():
    with pytest.raises(ValueError):
        model.evaluate_manual_plan_expiry(draft(), now=datetime(2026, 10, 14))
