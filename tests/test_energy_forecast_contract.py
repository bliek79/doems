from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
import sys
import types
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"
FORBIDDEN_ACTIVE_IDENTITIES = ("dummy_os_data", "Dummy OS Data", "dummy_os_energy", "Dummy OS Energy")


def _load_pure_module(name: str):
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components"); package.__path__ = [str(ROOT / "custom_components")]; sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems"); package.__path__ = [str(INTEGRATION)]; sys.modules["custom_components.doems"] = package
    return importlib.import_module(f"custom_components.doems.{name}")


def test_manifest_and_clean_identity_contract() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "doems" and manifest["name"] == "DOEMS" and manifest["version"] == "0.1.0-alpha.7.19"
    for path in INTEGRATION.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".json", ".yaml", ".yml"}: continue
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_ACTIVE_IDENTITIES: assert forbidden not in text, f"{forbidden!r} found in {path}"


def test_public_entity_object_ids_are_doems_prefixed() -> None:
    suggested=[]; unique=[]
    for path in [INTEGRATION / "sensor.py", INTEGRATION / "solar_sensor.py", INTEGRATION / "prices_sensor.py", INTEGRATION / "select.py", INTEGRATION / "binary_sensor.py", INTEGRATION / "switch.py", INTEGRATION / "datetime.py"]:
        tree=ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node,(ast.Assign,ast.AnnAssign)): continue
            targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            value=node.value
            if not isinstance(value,ast.Constant) or not isinstance(value.value,str): continue
            for target in targets:
                if isinstance(target,ast.Name) and target.id=="_attr_suggested_object_id": suggested.append(value.value)
                if isinstance(target,ast.Name) and target.id=="_attr_unique_id": unique.append(value.value)
    assert suggested and unique
    assert all(v.startswith("doems_") for v in suggested + unique)


def test_no_physical_control_surface() -> None:
    active_text="\n".join(path.read_text(encoding="utf-8") for path in INTEGRATION.rglob("*.py"))
    assert active_text.count(".services.async_call(") == 1
    prices=(INTEGRATION / "prices.py").read_text(encoding="utf-8")
    assert '"energyzero"' in prices and '"get_gas_prices"' in prices
    for forbidden in ('"anker_solix"', '"switch"', '"number"', '"select.select_option"'):
        assert forbidden not in prices
    assert '"physical_execution_authority": False' in active_text


def test_install_contract_is_component_scoped() -> None:
    text=(INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    const=(INTEGRATION / "const.py").read_text(encoding="utf-8")
    for token in ("direct_home_power","power_balance","grid_sign_convention","battery_present"):
        assert token in text or token in const
    for token in ("solar_foundation_enabled","solar_location_source","solar_inverter_groups","solar_arrays","solar_latitude","solar_longitude"):
        assert token in text or token in const
    for token in ("ems_enabled","battery_capacity_kwh","technical_min_soc_percent","max_soc_percent","max_charge_power_w","max_discharge_power_w","software_reserve_percent","charge_efficiency_percent","discharge_efficiency_percent","minimum_trade_margin_eur_per_kwh","startup_delay_seconds"):
        assert token in text or token in const
    assert "physical_execution" not in text
    config_flow=(INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    assert "validate_ems_combination(normalized)" in config_flow
    validation=(INTEGRATION / "ems_config_validation.py").read_text(encoding="utf-8")
    for token in ("EMS_VALIDATED_FIELDS","validate_ems_combination","ems_invalid_number","ems_below_minimum","ems_above_maximum","ems_invalid_step","ems_soc_range_invalid"):
        assert token in validation
    assert "CONF_AWAY_START" not in validation
    assert "CONF_AWAY_END" not in validation
    assert "CONF_AWAY_SCHEDULE_ENABLED" not in validation
    settings=(INTEGRATION / "ems_settings.py").read_text(encoding="utf-8")
    for token in ("EMSSettings","battery_capacity_kwh","technical_min_soc_percent","max_soc_percent","max_charge_power_w","max_discharge_power_w","software_reserve_percent","charge_efficiency_percent","discharge_efficiency_percent","minimum_trade_margin_eur_per_kwh","startup_delay_seconds"):
        assert token in settings
    init=(INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    assert "EMSSettings.from_options(entry.options)" in init


def test_alpha41_equivalent_forecast_shape_and_hierarchy() -> None:
    m=_load_pure_module("energy_forecast")
    records=[{"start":"2026-09-08T10:15:00+00:00","end":"2026-09-08T10:30:00+00:00","energy_kwh":0.25,"profile":"normal","valid":True}]
    model=m.EnergyBaselineForecast(records,local_timezone=timezone.utc)
    slots=model.build("normal",now=datetime(2026,9,15,10,7,tzinfo=timezone.utc))
    assert len(slots)==288 and slots[0].start.isoformat()=="2026-09-15T10:15:00+00:00" and slots[-1].end.isoformat()=="2026-09-18T10:15:00+00:00"
    assert slots[0].energy_kwh==0.25 and slots[0].source=="weekday_quarter" and slots[0].confidence==0.66
    assert round(sum(slot.energy_kwh or 0.0 for slot in slots),6)==72.0


def test_profile_without_history_does_not_borrow_other_profile() -> None:
    m=_load_pure_module("energy_forecast")
    records=[{"start":"2026-09-08T10:15:00+00:00","energy_kwh":0.25,"profile":"normal","valid":True}]
    slots=m.EnergyBaselineForecast(records,local_timezone=timezone.utc).build("away",now=datetime(2026,9,15,10,7,tzinfo=timezone.utc))
    assert len(slots)==288 and all(slot.energy_kwh is None for slot in slots)


def test_power_balance_and_sign_normalization() -> None:
    s=_load_pure_module("energy_sources")
    assert s.normalize_power_w("1.25","kW",allow_negative=False)==1250.0
    assert s.normalize_grid_net_w(500.0,"positive_import_negative_export")==500.0
    assert s.normalize_grid_net_w(500.0,"positive_export_negative_import")==-500.0
    assert s.home_power_from_balance_w(grid_net_w=500.0,solar_w=1000.0,battery_charge_w=200.0,battery_discharge_w=50.0)==1350.0


def test_source_signature_changes_when_semantics_change() -> None:
    s=_load_pure_module("energy_sources")
    base={"energy_source_mode":"power_balance","grid_net_power_entity":"sensor.grid","grid_sign_convention":"positive_import_negative_export","solar_power_entity":"sensor.solar","battery_present":False}
    flipped=dict(base); flipped["grid_sign_convention"]="positive_export_negative_import"
    assert s.source_signature(base)!=s.source_signature(flipped)


def test_startup_source_recovery_refresh_is_one_shot_and_component_scoped() -> None:
    text=(INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    assert "async_track_state_change_event" in text
    assert "if not coordinator.source_available" in text
    assert "coordinator.source_entities" in text
    assert "coordinator._notify()" in text
    assert "remove_listener()" in text
