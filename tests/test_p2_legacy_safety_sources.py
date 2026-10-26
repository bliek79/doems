"""Behavioral checks for the read-only legacy EMS emergency safety gate."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def safety(monkeypatch):
    ha = ModuleType("homeassistant")
    helpers = ModuleType("homeassistant.helpers")
    registry = ModuleType("homeassistant.helpers.entity_registry")
    helpers.entity_registry = registry
    ha.helpers = helpers
    for key, mod in (
        ("homeassistant", ha),
        ("homeassistant.helpers", helpers),
        ("homeassistant.helpers.entity_registry", registry),
    ):
        monkeypatch.setitem(sys.modules, key, mod)
    path = Path(__file__).resolve().parents[1] / "custom_components/doems/legacy_ems_safety.py"
    spec = importlib.util.spec_from_file_location("p2_test_legacy_safety", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    ids = {
        "arm": ("switch.legacy_arm", "switch", "abc_automatic_execution_arm"),
        "execution": ("sensor.legacy_execution", "sensor", "abc_execution_status"),
        "physical_test": ("sensor.legacy_test", "sensor", "abc_physical_test_status"),
        "preflight": ("sensor.legacy_preflight", "sensor", "abc_automatic_execution_preflight"),
    }
    entities = {
        key: SimpleNamespace(entity_id=value[0], domain=value[1], unique_id=value[2],
                             platform="anker_ems", disabled_by=None)
        for key, value in ids.items()
    }
    states = {
        "switch.legacy_arm": SimpleNamespace(state="off", attributes={}),
        "sensor.legacy_execution": SimpleNamespace(state="idle", attributes={"active": False}),
        "sensor.legacy_test": SimpleNamespace(state="idle", attributes={"active": False}),
        "sensor.legacy_preflight": SimpleNamespace(state="ready", attributes={"mode_switch_live_active": False}),
    }
    registry.async_get = lambda hass: SimpleNamespace(entities=entities)
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get))
    return SimpleNamespace(read=module.read_legacy_safety, hass=hass, states=states, entities=entities)


def test_all_four_explicitly_safe(safety):
    assert safety.read(safety.hass) == {"automatic_armed": False, "physical_test": {"active": False}}


@pytest.mark.parametrize("role,attribute", [
    ("execution", "active"),
    ("physical_test", "active"),
    ("preflight", "mode_switch_live_active"),
])
@pytest.mark.parametrize("value", [True, None, "false", 0])
def test_activity_not_explicit_boolean_false_blocks(safety, role, attribute, value):
    suffix = {"execution": "execution", "physical_test": "test", "preflight": "preflight"}[role]
    state = safety.states[f"sensor.legacy_{suffix}"]
    state.attributes[attribute] = value
    with pytest.raises(ValueError):
        safety.read(safety.hass)


@pytest.mark.parametrize("value", ["on", "unknown", "unavailable", ""])
def test_arm_must_be_explicit_off(safety, value):
    safety.states["switch.legacy_arm"].state = value
    with pytest.raises(ValueError):
        safety.read(safety.hass)


def test_missing_or_duplicate_registry_entries_block(safety):
    safety.entities.pop("execution")
    with pytest.raises(ValueError):
        safety.read(safety.hass)


def test_missing_state_blocks(safety):
    safety.states.pop("sensor.legacy_test")
    with pytest.raises(ValueError):
        safety.read(safety.hass)
