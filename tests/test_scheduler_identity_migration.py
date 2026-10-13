"""Permanent public Scheduler name and idempotent registry migration."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from dataclasses import dataclass

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "doems"
OLD_ID = "doems_r7_scheduler_status"
NEW_ID = "doems_scheduler_status"
NEW_ENTITY_ID = "sensor.doems_scheduler_status"


@dataclass
class RegistryEntry:
    entity_id: str
    unique_id: str
    platform: str = "doems"


class FakeRegistry:
    def __init__(self, *entries):
        self.entities = {entry.entity_id: entry for entry in entries}
        self.updates = []
        self.removals = []

    def async_get_entity_id(self, domain, platform, unique_id):
        for entry in self.entities.values():
            if (
                domain == "sensor"
                and entry.platform == platform
                and entry.unique_id == unique_id
            ):
                return entry.entity_id
        return None

    def async_get(self, entity_id):
        return self.entities.get(entity_id)

    def async_remove(self, entity_id):
        self.removals.append(entity_id)
        self.entities.pop(entity_id, None)

    def async_update_entity(self, old_entity_id, *, new_unique_id, new_entity_id):
        old = self.entities.pop(old_entity_id)
        old.unique_id = new_unique_id
        old.entity_id = new_entity_id
        self.entities[new_entity_id] = old
        self.updates.append((old_entity_id, new_unique_id, new_entity_id))


def _load_migration(monkeypatch):
    def stub(name, **values):
        module = types.ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
        return module
    stub("homeassistant", __path__=[])
    stub("homeassistant.config_entries", ConfigEntry=object)
    stub("homeassistant.core", HomeAssistant=object)
    stub("homeassistant.helpers", __path__=[])
    entity_registry = stub("homeassistant.helpers.entity_registry", EntityRegistry=object)
    sys.modules["homeassistant.helpers"].entity_registry = entity_registry
    stub("custom_components", __path__=[])
    stub("custom_components.doems", __path__=[])
    stub("custom_components.doems.const", DOMAIN="doems")
    spec = importlib.util.spec_from_file_location(
        "custom_components.doems.planner_migration_name_test",
        COMPONENT / "planner_migration.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_sensor_identity_and_dashboard_are_phase_free():
    sensor = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    example = (ROOT / "examples" / "doems_scheduler_status_card.yaml").read_text(encoding="utf-8")
    assert '    _attr_name = "DOEMS Scheduler Status"' in sensor
    assert '    _attr_unique_id = "doems_scheduler_status"' in sensor
    assert '    _attr_suggested_object_id = "doems_scheduler_status"' in sensor
    assert "doems_r7_scheduler_status" not in sensor
    assert "DOEMS R7 Scheduler Status" not in sensor
    assert "sensor.doems_scheduler_status" in example
    assert "DOEMS R7" not in example
    assert not (ROOT / "examples" / "doems_r7_scheduler_status_card.yaml").exists()


def test_migration_mapping_is_single_permanent_target(monkeypatch):
    migration = _load_migration(monkeypatch)
    old_targets = [row for row in migration._ENTITY_MIGRATIONS if row[0] == OLD_ID]
    assert old_targets == [(OLD_ID, NEW_ID, NEW_ENTITY_ID)]


def test_already_correct_or_never_installed_is_noop(monkeypatch):
    migration = _load_migration(monkeypatch)
    for existing in ([], [RegistryEntry(NEW_ENTITY_ID, NEW_ID)]):
        registry = FakeRegistry(*existing)
        migration._migrate_entity(
            registry, old_unique_id=OLD_ID, new_unique_id=NEW_ID,
            new_entity_id=NEW_ENTITY_ID,
        )
        assert not registry.updates
        assert not registry.removals


def test_old_entity_keeps_identity_and_migrates_only_once(monkeypatch):
    migration = _load_migration(monkeypatch)
    registry = FakeRegistry(RegistryEntry("sensor.doems_r7_scheduler_status", OLD_ID))
    for _ in range(2):
        migration._migrate_entity(
            registry, old_unique_id=OLD_ID, new_unique_id=NEW_ID,
            new_entity_id=NEW_ENTITY_ID,
        )
    assert registry.updates == [
        ("sensor.doems_r7_scheduler_status", NEW_ID, NEW_ENTITY_ID)
    ]
    assert list(registry.entities) == [NEW_ENTITY_ID]
    assert registry.entities[NEW_ENTITY_ID].unique_id == NEW_ID


def test_existing_correct_target_wins_without_duplicate(monkeypatch):
    migration = _load_migration(monkeypatch)
    registry = FakeRegistry(
        RegistryEntry("sensor.doems_r7_scheduler_status", OLD_ID),
        RegistryEntry(NEW_ENTITY_ID, NEW_ID),
    )
    migration._migrate_entity(
        registry, old_unique_id=OLD_ID, new_unique_id=NEW_ID,
        new_entity_id=NEW_ENTITY_ID,
    )
    assert registry.removals == ["sensor.doems_r7_scheduler_status"]
    assert not registry.updates
    assert list(registry.entities) == [NEW_ENTITY_ID]


def test_foreign_collision_fails_without_removing_anything(monkeypatch):
    migration = _load_migration(monkeypatch)
    registry = FakeRegistry(
        RegistryEntry("sensor.doems_r7_scheduler_status", OLD_ID),
        RegistryEntry(NEW_ENTITY_ID, "foreign_unique_id", "other_integration"),
    )
    with pytest.raises(RuntimeError, match="migration collision"):
        migration._migrate_entity(
            registry, old_unique_id=OLD_ID, new_unique_id=NEW_ID,
            new_entity_id=NEW_ENTITY_ID,
        )
    assert len(registry.entities) == 2
    assert not registry.removals
    assert not registry.updates
