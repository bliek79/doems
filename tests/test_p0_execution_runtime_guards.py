"""P0 runtime regression guards: startup reconciliation and stop classification."""
from pathlib import Path

RUNTIME = Path("custom_components/doems/combined_execution_shadow_runtime.py")


def test_runtime_has_restart_reconciliation_fence():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "require_restart_reconciliation()" in source
    assert 'mode == "third_party_control"' in source
    assert "await self.controller.stop()" in source
    assert "self._restart_reconciled = True" in source


def test_watchdog_safety_stop_is_not_success():
    source = RUNTIME.read_text(encoding="utf-8")
    assert '"voltooid" if normal else "fout"' in source
    assert '"execution_completed" if normal else "execution_safety_stopped"' in source


def test_execution_stays_default_off():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "entities=None, authority=False" in source
    assert "self._authority = bool(authority)" in source
