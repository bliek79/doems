from __future__ import annotations
import importlib
from pathlib import Path
import sys
import types
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"

def _load_settings():
    if "custom_components" not in sys.modules:
        package=types.ModuleType("custom_components"); package.__path__=[str(ROOT/"custom_components")]; sys.modules["custom_components"]=package
    if "custom_components.doems" not in sys.modules:
        package=types.ModuleType("custom_components.doems"); package.__path__=[str(INTEGRATION)]; sys.modules["custom_components.doems"]=package
    return importlib.import_module("custom_components.doems.ems_settings")

def test_default_settings_keep_proven_live_values_and_alpha76_soc_bounds() -> None:
    m=_load_settings(); settings=m.EMSSettings.from_options({})
    assert settings.as_contract()=={
        "battery_capacity_kwh":7.2,"technical_min_soc_percent":5,"max_soc_percent":100,
        "max_charge_power_w":3200,"max_discharge_power_w":3200,"software_reserve_percent":7.0,
        "charge_efficiency_percent":92.0,"discharge_efficiency_percent":92.0,
        "minimum_trade_margin_eur_per_kwh":0.10,"startup_delay_seconds":30,
    }

def test_legacy_soc_options_cannot_change_frozen_alpha76_bounds() -> None:
    m=_load_settings()
    options={"battery_capacity_kwh":8.4,"technical_min_soc_percent":6,"max_soc_percent":95,
             "max_charge_power_w":3000,"max_discharge_power_w":2900,"software_reserve_percent":9.0,
             "charge_efficiency_percent":93.0,"discharge_efficiency_percent":91.0,
             "minimum_trade_margin_eur_per_kwh":0.17,"startup_delay_seconds":45}
    c=m.EMSSettings.from_options(options).as_contract()
    assert c["technical_min_soc_percent"]==5
    assert c["max_soc_percent"]==100
    for key in ("battery_capacity_kwh","max_charge_power_w","max_discharge_power_w","software_reserve_percent","charge_efficiency_percent","discharge_efficiency_percent","minimum_trade_margin_eur_per_kwh","startup_delay_seconds"):
        assert c[key]==options[key]

def test_snapshot_is_immutable_and_has_no_away_runtime_fields() -> None:
    m=_load_settings(); settings=m.EMSSettings.from_options({})
    assert settings.__dataclass_params__.frozen is True
    for key in ("away_schedule_enabled","away_start","away_end","effective_profile"):
        assert key not in settings.as_contract()
