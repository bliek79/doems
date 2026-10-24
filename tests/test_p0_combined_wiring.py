"""Structural regression guards for disarmed Combined wiring."""
from pathlib import Path

ROOT = Path("custom_components/doems")


def test_combined_snapshot_wired():
    setup = (ROOT / "__init__.py").read_text()
    runtime = (ROOT / "combined_execution_shadow_runtime.py").read_text()
    bridge = (ROOT / "combined_anker_bridge.py").read_text()
    assert "planner=planner, battery=battery_input" in setup
    assert "CombinedAnkerBridge(" in runtime
    assert "authority=False, exclusive=False" in runtime
    assert 'self.planner.snapshot("combined")' in bridge


def test_all_actuators_configurable():
    options = (ROOT / "config_flow.py").read_text()
    setup = (ROOT / "__init__.py").read_text()
    for name in ("CONF_ANKER_OPERATING_MODE_ENTITY", "CONF_ANKER_ACTION_DIRECTION_ENTITY", "CONF_ANKER_POWER_SETPOINT_ENTITY"):
        assert name in options
        assert name in setup


def test_execution_defaults_disarmed():
    runtime = (ROOT / "combined_execution_shadow_runtime.py").read_text()
    assert "entities=None, authority=False" in runtime
    assert "authority=False, exclusive=False" in runtime
