"""Regression checks for measured automatic plan energy stop."""
from datetime import datetime, timedelta, timezone

from custom_components.doems.execution_energy_meter import (
    planned_energy_reached, sample_energy,
)


def test_integrates_measured_watts_and_stops_at_energy_target():
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    state = sample_energy({}, now, 1000)
    state = sample_energy(state, now + timedelta(seconds=30), 1000)
    assert abs(state["energy_wh"] - 1000 * 30 / 3600) < 0.0001
    assert planned_energy_reached(state, 0.008)
    assert not planned_energy_reached(state, 0.012)


def test_caps_missing_sample_gap_at_60_seconds():
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    state = sample_energy({}, now, 500)
    state = sample_energy(state, now + timedelta(minutes=5), 500)
    assert abs(state["energy_wh"] - 500 * 60 / 3600) < 0.0001


def test_missing_and_invalid_samples_never_invent_energy():
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    state = sample_energy({}, now, None)
    assert state == {}
    state = sample_energy(state, now, float("nan"))
    assert state == {}
    assert not planned_energy_reached(state, None)
