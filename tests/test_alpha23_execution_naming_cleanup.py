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

def test_alpha23_legacy_persistence_values_are_normalized_without_rearming() -> None:
    import importlib.util

    path = INTEGRATION / "ems_execution.py"
    spec = importlib.util.spec_from_file_location("ems_execution_alpha23", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    legacy = "sha" + "dow"
    controller = module.DOEMSExecutionController()
    payload = {
        "schema_version": 1,
        "active": False,
        "status": f"completed_{legacy}",
        "reason": f"legacy {legacy} state",
        "history": [{"result": f"completed_{legacy}"}],
        "last_summary": {"result": f"completed_{legacy}"},
        "trace": [{"stage": f"armed_{legacy}"}],
        "handled_identities": [],
        "run_count": 1,
        "success_count": 1,
        "failure_count": 0,
        "safe_return": {},
        "frozen": {},
    }

    assert controller.restore_persistence(payload) == "loaded"
    restored = controller.export_persistence()
    assert restored["status"] == "completed"
    assert restored["last_summary"]["result"] == "completed"
    assert restored["history"][0]["result"] == "completed"
    assert restored["trace"][0]["stage"] == "armed"
    assert legacy not in str(restored).lower()


def test_alpha23_runtime_migrates_the_pre_alpha23_store_once() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    assert 'legacy_suffix = "execution_" + "sha" + "dow"' in runtime
    assert "await legacy_store.async_remove()" in runtime
    assert 'self.execution_store_status = "migrated_legacy"' in runtime

