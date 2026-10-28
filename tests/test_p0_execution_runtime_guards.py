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


def test_bridge_claim_and_disarm_are_symmetric():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "self._combined_bridge.authority = True" in source
    assert "self._combined_bridge.exclusive = True" in source
    assert "self._combined_bridge.authority = False" in source
    assert "self._combined_bridge.exclusive = False" in source


def test_runtime_watchdog_checks_direction_and_conflicting_flow():
    source = RUNTIME.read_text(encoding="utf-8")
    assert 'self.adapter._state("action_direction")' in source
    assert 'self._non_conflicting_power(snapshot.get("discharge_power_w"))' in source
    assert 'self._non_conflicting_power(snapshot.get("charge_power_w"))' in source


def test_mode_switch_allows_unavailable_pre_mode_setpoint_but_checks_post_mode_zero():
    source = Path("custom_components/doems/execution_anker_adapter.py").read_text(encoding="utf-8")
    assert 'if self._state("power_setpoint") is not None:' in source
    assert 'await self._wait(self._power_zero, timeout=15)' in source
    assert 'post_mode_ready") is True' in source
