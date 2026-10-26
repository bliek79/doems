"""Regression contract based on the proven dummy-os-anker-ems control path."""
from pathlib import Path

ROOT = Path("custom_components/doems")


def test_adapter_uses_proven_two_stage_mode_switch():
    source = (ROOT / "execution_anker_adapter.py").read_text(encoding="utf-8")
    assert 'self._state("operating_mode") != SELF_MODE' in source
    assert "observe_control_path(" in source
    assert "timeout=150" in source
    assert '("charge" if action == "laden" else "discharge")' in source
    assert "await self._wait(lambda: self._power_matches(applied_w))" in source
    assert "applied_w = await self._write_charge_power(power_w)" in source


def test_proven_five_second_monitor_and_default_shadow():
    source = (ROOT / "combined_execution_shadow_runtime.py").read_text(encoding="utf-8")
    assert "timedelta(seconds=5)" in source
    assert "entities=None, authority=False" in source
    assert "require_restart_reconciliation()" in source


def test_safe_return_checks_zero_and_mode():
    source = (ROOT / "execution_anker_adapter.py").read_text(encoding="utf-8")
    assert "await self._wait(lambda: self._power_zero(), timeout=15)" in source
    assert "self._state(\"operating_mode\") != SELF_MODE" in source
