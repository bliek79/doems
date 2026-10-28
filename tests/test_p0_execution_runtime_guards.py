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


def test_only_canonical_r8_route_gets_authority():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "authority=False, exclusive=False, controller=self.controller" in source
    assert "self._combined_bridge.authority = True" not in source
    assert "self._combined_bridge.exclusive = True" not in source
    assert "self.controller is self._combined_bridge.controller" in source


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


def test_passive_r9_bridge_cannot_stop_canonical_r8_session():
    source = RUNTIME.read_text(encoding="utf-8")
    assert 'self._combined_bridge.async_reconcile(' not in source
    assert '"bridge": "non_actuating_r9"' in source


def test_watchdog_requires_both_battery_power_sources():
    source = RUNTIME.read_text(encoding="utf-8")
    assert 'self._valid_battery_power(snapshot.get("charge_power_w"))' in source
    assert 'self._valid_battery_power(snapshot.get("discharge_power_w"))' in source


def test_charge_cap_update_is_serialized_with_safe_stop():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "async with self.adapter._lock:" in source
    assert 'ValueError("Execution disarmed during charge-limit update")' in source


def test_operator_master_off_cancels_only_after_verified_stop():
    source = RUNTIME.read_text(encoding="utf-8")
    assert '"geannuleerd"' in source
    assert '"manual_execution_disabled"' in source
    assert "await self.controller.stop()" in source
