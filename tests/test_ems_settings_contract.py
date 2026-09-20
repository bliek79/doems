from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load_settings():
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    return importlib.import_module("custom_components.doems.ems_settings")


def test_step5a_default_settings_snapshot_matches_config_contract() -> None:
    m = _load_settings()
    settings = m.EMSSettings.from_options({})
    assert settings.as_contract() == {
        "battery_capacity_kwh": 7.2,
        "technical_min_soc_percent": 5,
        "max_soc_percent": 100,
        "max_charge_power_w": 3200,
        "max_discharge_power_w": 3200,
        "software_reserve_percent": 7.0,
        "charge_efficiency_percent": 92.0,
        "discharge_efficiency_percent": 92.0,
        "minimum_trade_margin_eur_per_kwh": 0.10,
        "startup_delay_seconds": 30,
    }


def test_step5a_all_ten_options_are_read_exactly_once_into_snapshot() -> None:
    m = _load_settings()
    options = {
        "battery_capacity_kwh": 8.4,
        "technical_min_soc_percent": 6,
        "max_soc_percent": 95,
        "max_charge_power_w": 3000,
        "max_discharge_power_w": 2900,
        "software_reserve_percent": 9.0,
        "charge_efficiency_percent": 93.0,
        "discharge_efficiency_percent": 91.0,
        "minimum_trade_margin_eur_per_kwh": 0.17,
        "startup_delay_seconds": 45,
    }
    settings = m.EMSSettings.from_options(options)
    assert settings.as_contract() == options


def test_step5a_snapshot_is_immutable_and_has_no_away_runtime_fields() -> None:
    m = _load_settings()
    settings = m.EMSSettings.from_options({})
    assert settings.__dataclass_params__.frozen is True
    contract = settings.as_contract()
    for key in ("away_schedule_enabled", "away_start", "away_end", "effective_profile"):
        assert key not in contract


def test_step5a_runtime_binds_snapshot_only_when_ems_enabled() -> None:
    text = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    assert "EMSSettings.from_options(entry.options)" in text
    assert 'entry.options.get(CONF_EMS_ENABLED, False)' in text
    assert '"ems_settings": ems_settings' in text


def test_step5a_live_diagnostics_are_read_only_and_non_actuating() -> None:
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    assert "class DOEMSEMSSettingsSensor" in sensor
    assert 'doems_ems_settings' in sensor
    assert '"settings_source": "config_entry_options"' in sensor
    assert '"settings_snapshot_immutable": True' in sensor
    assert '"startup_delay_runtime_gate_active": False' in sensor
    assert '"planner_logic_active": self.shadow is not None' in sensor
    assert '"shadow_runtime_status": self.shadow.status if self.shadow is not None else None' in sensor
    assert '"physical_execution_authority": False' in sensor


def test_step5a_settings_layer_does_not_itself_activate_startup_gate() -> None:
    settings = (INTEGRATION / "ems_settings.py").read_text(encoding="utf-8")
    assert "startup_delay_seconds" in settings
    assert ".services.async_call(" not in settings
    assert "planner" not in settings.lower()
    init = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    assert "asyncio.sleep" not in init
