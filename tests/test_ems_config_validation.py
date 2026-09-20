from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load_validation():
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    return importlib.import_module("custom_components.doems.ems_config_validation")


def test_step4a_static_ems_fields_are_covered() -> None:
    m = _load_validation()
    assert set(m.EMS_VALIDATED_FIELDS) == {
        "battery_capacity_kwh",
        "technical_min_soc_percent",
        "max_soc_percent",
        "max_charge_power_w",
        "max_discharge_power_w",
        "software_reserve_percent",
        "charge_efficiency_percent",
        "discharge_efficiency_percent",
        "minimum_trade_margin_eur_per_kwh",
        "startup_delay_seconds",
    }


def test_step4a_numeric_boundaries_and_steps() -> None:
    m = _load_validation()
    valid = {
        "battery_capacity_kwh": (1.0, 7.2, 30.0),
        "technical_min_soc_percent": (0, 5, 30),
        "max_soc_percent": (50, 100),
        "max_charge_power_w": (100, 3200, 3500),
        "max_discharge_power_w": (100, 3200, 3500),
        "software_reserve_percent": (0, 7, 30),
        "charge_efficiency_percent": (50, 92, 100),
        "discharge_efficiency_percent": (50, 92, 100),
        "minimum_trade_margin_eur_per_kwh": (0.00, 0.10, 1.00),
        "startup_delay_seconds": (30, 35, 300),
    }
    for key, values in valid.items():
        for value in values:
            assert m.validate_ems_field(key, value) is None, (key, value)

    assert m.validate_ems_field("battery_capacity_kwh", 0.9) == m.ERR_BELOW_MINIMUM
    assert m.validate_ems_field("battery_capacity_kwh", 30.1) == m.ERR_ABOVE_MAXIMUM
    assert m.validate_ems_field("battery_capacity_kwh", 7.25) == m.ERR_INVALID_STEP
    assert m.validate_ems_field("technical_min_soc_percent", 5.5) == m.ERR_INVALID_STEP
    assert m.validate_ems_field("max_charge_power_w", 101) == m.ERR_INVALID_STEP
    assert m.validate_ems_field("max_discharge_power_w", 3600) == m.ERR_ABOVE_MAXIMUM
    assert m.validate_ems_field("software_reserve_percent", 7.5) == m.ERR_INVALID_STEP
    assert m.validate_ems_field("charge_efficiency_percent", 92.5) == m.ERR_INVALID_STEP
    assert m.validate_ems_field("minimum_trade_margin_eur_per_kwh", 0.105) == m.ERR_INVALID_STEP
    assert m.validate_ems_field("startup_delay_seconds", 34) == m.ERR_INVALID_STEP
    assert m.validate_ems_field("startup_delay_seconds", 25) == m.ERR_BELOW_MINIMUM
    assert m.validate_ems_field("startup_delay_seconds", 305) == m.ERR_ABOVE_MAXIMUM


def test_step4a_rejects_wrong_numeric_types() -> None:
    m = _load_validation()
    assert m.validate_ems_field("battery_capacity_kwh", "not-a-number") == m.ERR_INVALID_NUMBER
    assert m.validate_ems_field("battery_capacity_kwh", True) == m.ERR_INVALID_NUMBER


def test_step4b_soc_combination_validation_remains_in_options() -> None:
    m = _load_validation()
    assert m.validate_ems_combination({
        "technical_min_soc_percent": 5,
        "max_soc_percent": 100,
    }) == {}
    assert m.validate_ems_combination({
        "technical_min_soc_percent": 30,
        "max_soc_percent": 30,
    }) == {"max_soc_percent": m.ERR_SOC_RANGE_INVALID}
    assert m.validate_ems_combination({
        "technical_min_soc_percent": 30,
        "max_soc_percent": 20,
    }) == {"max_soc_percent": m.ERR_SOC_RANGE_INVALID}


def test_away_is_not_an_ems_options_validation_field() -> None:
    m = _load_validation()
    for key in ("away_schedule_enabled", "away_start", "away_end"):
        assert key not in m.EMS_VALIDATED_FIELDS
