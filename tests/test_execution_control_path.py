"""Contract tests for Anker control-path observation without actuation."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.doems.execution_control_path import observe_control_path


class States:
    def __init__(self, values):
        self.values = values

    def get(self, entity_id):
        return self.values.get(entity_id)


def test_pre_mode_does_not_require_hidden_external_controls():
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    entities = {"operating_mode": "select.mode", "action_direction": "select.direction",
                "power_setpoint": "number.power"}
    hass = SimpleNamespace(states=States({
        "select.mode": SimpleNamespace(state="self_consumption", last_changed=now-timedelta(seconds=70)),
        "select.direction": SimpleNamespace(state="unavailable", last_changed=now),
        "number.power": SimpleNamespace(state="unavailable", last_changed=now),
    }))
    result = observe_control_path(hass, entities, now)
    assert result["ready"] is True
    assert result["post_mode_ready"] is False
    assert result["physical_execution_enabled"] is False


def test_external_controls_require_stability():
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    entities = {"operating_mode": "select.mode", "action_direction": "select.direction",
                "power_setpoint": "number.power"}
    hass = SimpleNamespace(states=States({
        "select.mode": SimpleNamespace(state="third_party_control", last_changed=now-timedelta(seconds=70)),
        "select.direction": SimpleNamespace(state="charge", last_changed=now-timedelta(seconds=70)),
        "number.power": SimpleNamespace(state="0", last_changed=now-timedelta(seconds=30)),
    }))
    assert observe_control_path(hass, entities, now)["ready"] is False
    hass.states.values["number.power"].last_changed = now-timedelta(seconds=70)
    assert observe_control_path(hass, entities, now)["ready"] is True


def test_invalid_control_path_fails_closed():
    result = observe_control_path(SimpleNamespace(states=States({})), {}, datetime.now(timezone.utc))
    assert result["ready"] is False
    assert len(result["blockers"]) == 3
