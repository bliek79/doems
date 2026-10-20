"""R8 integration boundary: no physical authorization from readiness alone."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "doems"


def load(name):
    spec = importlib.util.spec_from_file_location("r8_test_" + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


handover = load("execution_handover")
control = load("execution_control_path")


class FakeHass:
    def __init__(self, states):
        self.states = SimpleNamespace(get=states.get)


def state(value, now, age=90):
    return SimpleNamespace(state=value, last_changed=now - timedelta(seconds=age))


ENTITIES = {
    "operating_mode": "select.battery_mode",
    "action_direction": "select.battery_direction",
    "power_setpoint": "number.battery_power",
}


def test_handover_never_grants_physical_authority_even_when_all_gates_pass():
    result = handover.assess_handover(
        control_path={"ready": True},
        command_contract_verified=True,
        exclusive_authority_verified=True,
        restart_reconciled=True,
        live_stop_test_passed=True,
    )
    assert result["ready_for_handover"] is True
    assert result["physical_execution_enabled"] is False
    assert result["execution_authority"] is False


def test_handover_missing_exclusivity_blocks():
    result = handover.assess_handover(
        control_path={"ready": True},
        command_contract_verified=True,
        exclusive_authority_verified=False,
        restart_reconciled=True,
        live_stop_test_passed=True,
    )
    assert result["ready_for_handover"] is False
    assert "exclusive_authority_not_verified" in result["blockers"]


def test_control_path_unconfigured_is_blocked():
    result = control.observe_control_path(FakeHass({}), {}, datetime.now(timezone.utc))
    assert result["ready"] is False
    assert result["physical_execution_enabled"] is False


def test_control_path_stable_self_consumption_is_observation_only():
    now = datetime.now(timezone.utc)
    hass = FakeHass({
        ENTITIES["operating_mode"]: state(control.SELF_MODE, now),
        ENTITIES["action_direction"]: state("charge", now),
        ENTITIES["power_setpoint"]: state("0", now),
    })
    result = control.observe_control_path(hass, ENTITIES, now)
    assert result["ready"] is True
    assert result["external_mode_active"] is False
    assert result["execution_authority"] is False
    assert result["physical_execution_enabled"] is False


def test_control_path_external_mode_requires_stable_controls():
    now = datetime.now(timezone.utc)
    hass = FakeHass({
        ENTITIES["operating_mode"]: state(control.EXTERNAL_MODE, now),
        ENTITIES["action_direction"]: state("charge", now, age=5),
        ENTITIES["power_setpoint"]: state("0", now),
    })
    result = control.observe_control_path(hass, ENTITIES, now)
    assert result["ready"] is False
    assert "external_controls_not_stable_or_unavailable" in result["blockers"]


def test_control_path_external_mode_stable_is_still_not_authority():
    now = datetime.now(timezone.utc)
    hass = FakeHass({
        ENTITIES["operating_mode"]: state(control.EXTERNAL_MODE, now),
        ENTITIES["action_direction"]: state("charge", now),
        ENTITIES["power_setpoint"]: state("0", now),
    })
    result = control.observe_control_path(hass, ENTITIES, now)
    assert result["ready"] is True
    assert result["execution_authority"] is False
    assert result["physical_execution_enabled"] is False
