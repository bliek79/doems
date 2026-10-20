"""R8 Alpha76 observation bridge unit tests; no Home Assistant required."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path
import importlib.util

p = Path(__file__).resolve().parents[1] / "custom_components/doems/execution_alpha76_bridge.py"
spec = importlib.util.spec_from_file_location("execution_alpha76_bridge", p)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _runtime(updated, soc=45, status="ok", active=False):
    return SimpleNamespace(
        data={"scheduler_ready": True},
        soc_percent=soc,
        soc_last_updated=updated,
        soc_source_status=status,
        execution=SimpleNamespace(data={"active": active, "slot": 1, "origin": "manual"}),
        _setpoint_handoff_status="idle",
    )


def test_fresh_soc_is_observed_but_direction_is_not_invented():
    now = datetime.now(timezone.utc)
    result = module.observe_alpha76(_runtime(now.isoformat(), active=True), now)
    assert result["battery"]["status"] == "ready"
    assert result["battery"]["soc_percent"] == 45
    assert result["battery"]["direction_consistent"] is False
    assert result["proven_execution"]["active"] is True
    assert result["proven_execution"]["physical_owner"] == "alpha76"
    assert result["proven_execution"]["r8_command_issued"] is False


def test_stale_missing_and_invalid_soc_fail_closed():
    now = datetime.now(timezone.utc)
    for rt in (
        _runtime((now - timedelta(minutes=6)).isoformat()),
        _runtime(None),
        _runtime(now.isoformat(), soc=float("nan")),
        _runtime(now.isoformat(), status="unavailable"),
    ):
        result = module.observe_alpha76(rt, now)
        assert result["battery"]["status"] == "blocked"
        assert result["source_fresh"] is False or result["battery"]["soc_percent"] is None
