from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_presence_store_and_entities_exist() -> None:
    required = {
        "presence.py",
        "select.py",
        "switch.py",
        "datetime.py",
        "binary_sensor.py",
        "sensor.py",
    }
    assert required <= {p.name for p in INTEGRATION.iterdir() if p.is_file()}

    select = (INTEGRATION / "select.py").read_text(encoding="utf-8")
    switch = (INTEGRATION / "switch.py").read_text(encoding="utf-8")
    dt = (INTEGRATION / "datetime.py").read_text(encoding="utf-8")
    binary = (INTEGRATION / "binary_sensor.py").read_text(encoding="utf-8")
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")

    for token in (
        "doems_presence_profile",
        "doems_away_schedule_enabled",
        "doems_away_start",
        "doems_away_end",
        "doems_away_active",
        "doems_away_schedule_valid",
        "doems_presence_context",
    ):
        assert token in select + switch + dt + binary + sensor


def test_presence_priority_and_fail_closed_contract_is_encoded() -> None:
    text = (INTEGRATION / "presence.py").read_text(encoding="utf-8")
    for token in (
        'PROFILE_UNCLASSIFIED',
        '"manual_override"',
        '"away_schedule"',
        '"invalid_away_schedule"',
        '"manual_profile_invalid"',
        "pre_schedule_profile",
        "manual_override_active",
        "restart_restored",
        "schedule_valid",
        "schedule_active",
        "blockers",
    ):
        assert token in text


def test_presence_store_is_persistent_and_schedules_boundaries() -> None:
    text = (INTEGRATION / "presence.py").read_text(encoding="utf-8")
    assert "Store(" in text
    assert "PRESENCE_STORAGE_KEY" in text
    assert "async_track_point_in_utc_time" in text
    assert "await self.store.async_save" in text
    assert "await self.store.async_load" in text


def test_away_runtime_is_not_exposed_in_options_form() -> None:
    config = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    ems_section = config.split("async def async_step_ems", 1)[1].split("async def async_step_prices", 1)[0]
    energy_section = config.split("async def async_step_energy_forecast", 1)[1].split("async def async_step_energy_direct", 1)[0]

    assert "CONF_AWAY_SCHEDULE_ENABLED" not in ems_section
    assert "CONF_AWAY_START" not in ems_section
    assert "CONF_AWAY_END" not in ems_section
    assert "DateTimeSelector" not in ems_section
    assert "CONF_ENERGY_START_PROFILE" not in energy_section


def test_legacy_away_options_are_migration_only() -> None:
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    config = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    presence = (INTEGRATION / "presence.py").read_text(encoding="utf-8")
    assert "Legacy Alpha7.10-7.12 Away Options keys" in const
    for token in ("CONF_AWAY_SCHEDULE_ENABLED", "CONF_AWAY_START", "CONF_AWAY_END"):
        assert token in presence
        assert token in config
    assert "Away/profile runtime state is owned by PresenceStore entities" in config


def test_presence_keeps_physical_execution_disabled() -> None:
    text = (INTEGRATION / "presence.py").read_text(encoding="utf-8")
    assert '"physical_execution_authority": False' in text
    assert ".services.async_call(" not in text
