"""Pure watchdog regression tests."""
from datetime import datetime, timedelta, timezone

from custom_components.doems.execution_watchdog import evaluate_session


def decision(**changes):
    now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    args = dict(now=now, started_at=now - timedelta(minutes=15),
                action="laden", target_soc=80, max_runtime_h=1,
                soc_percent=60, sources_fresh=True, controller_exclusive=True,
                command_acknowledged=True, plan_identity_matches=True,
                safety_clear=True)
    args.update(changes)
    return evaluate_session(**args)


def test_valid_session_continues():
    assert decision()["decision"] == "continue"


def test_target_reached_stops():
    assert "target_reached" in decision(soc_percent=80)["blockers"]


def test_runtime_elapsed_stops():
    now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    assert "runtime_elapsed" in decision(started_at=now - timedelta(hours=2))["blockers"]


def test_controller_conflict_stops():
    assert "controller_conflict" in decision(controller_exclusive=False)["blockers"]


def test_stale_sources_stop():
    assert "stale_sources" in decision(sources_fresh=False)["blockers"]


def test_changed_plan_stops():
    assert "active_plan_changed" in decision(plan_identity_matches=False)["blockers"]


def test_missing_acknowledgement_stops():
    assert "command_ack_lost" in decision(command_acknowledged=False)["blockers"]


def test_missing_start_timestamp_fails_closed():
    assert 'invalid_clock' in decision(started_at=None)['blockers']


def test_naive_start_timestamp_fails_closed():
    assert 'invalid_clock' in decision(started_at=datetime(2026, 10, 18, 11, 0))['blockers']
