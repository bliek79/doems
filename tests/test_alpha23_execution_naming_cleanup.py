from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_alpha23_active_integration_has_no_legacy_execution_term() -> None:
    forbidden = "sha" + "dow"
    active_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in INTEGRATION.rglob("*")
        if path.is_file() and path.suffix in {".py", ".json", ".yaml"}
    )
    assert forbidden not in active_text.lower()
    assert not any(forbidden in path.name.lower() for path in INTEGRATION.rglob("*"))


def test_alpha23_execution_contract_is_neutral_and_non_actuating() -> None:
    execution = (INTEGRATION / "ems_execution.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")

    assert "class DOEMSExecutionController" in execution
    assert '"execution_status": self._status' in execution
    assert '"execution_active": self._active' in execution
    assert '"execution_reason": self._reason' in execution
    assert '"execution_trace": list(self._trace)' in execution
    assert '"execution_run_history": list(self._history)' in execution

    for terminal in (
        '"completed"',
        '"emergency_stopped"',
        '"recovered_interrupted"',
    ):
        assert terminal in execution

    assert 'self._request_fast_refresh("execution_monitor")' in runtime
    assert '"execution_store_key": f"{DOMAIN}.{self.entry.entry_id}.execution"' in runtime
    assert "self.execution.evaluate(" in runtime
    assert '"physical_execution_authority": False' in execution
    assert '"service_calls_performed": False' in execution
    assert ".services.async_call(" not in execution

    assert '"execution_transaction"' in sensor
    assert '"execution_trace"' in sensor
    assert '"execution_run_history"' in sensor
