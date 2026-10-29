"""Exercise the real options flow with a small HA presentation adapter."""
from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
import sys
import types

import pytest
import voluptuous as vol

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def flow_module(monkeypatch):
    class FlowBase:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

    class Selector:
        def __init__(self, config=None):
            self.config = config

        def __call__(self, value):
            return value

    modules = {name: types.ModuleType(name) for name in (
        "homeassistant", "homeassistant.config_entries", "homeassistant.core",
        "homeassistant.helpers", "homeassistant.helpers.selector",
    )}
    entries = modules["homeassistant.config_entries"]
    entries.ConfigFlow = entries.OptionsFlow = FlowBase
    entries.ConfigEntry = object
    entries.ConfigFlowResult = dict
    modules["homeassistant"].config_entries = entries
    modules["homeassistant.core"].HomeAssistant = object
    modules["homeassistant.core"].callback = lambda fn: fn
    selectors = modules["homeassistant.helpers.selector"]
    for name in ("EntitySelector", "NumberSelector", "ConfigEntrySelector", "SelectSelector"):
        setattr(selectors, name, Selector)
    for name in ("EntitySelectorConfig", "NumberSelectorConfig", "SelectSelectorConfig", "SelectOptionDict"):
        setattr(selectors, name, dict)
    selectors.SelectSelectorMode = types.SimpleNamespace(DROPDOWN="dropdown")
    selectors.NumberSelectorMode = types.SimpleNamespace(BOX="box")
    modules["homeassistant.helpers"].selector = selectors
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    package = types.ModuleType("_plan72_config_test")
    package.__path__ = [str(ROOT / "custom_components/doems")]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    name = package.__name__ + ".config_flow"
    sys.modules.pop(name, None)
    module = importlib.import_module(name)
    yield module
    for key in tuple(sys.modules):
        if key.startswith("_plan72_config_test."):
            sys.modules.pop(key, None)


def make_flow(module, options=None):
    return module.DOEMSOptionsFlow(types.SimpleNamespace(options=options or {}))


def run(coro):
    return asyncio.run(coro)


def valid_plan_input(**changes):
    return {
        "plan72_max_charge_power_w": 3200,
        "plan72_max_discharge_power_w": 3200,
        "plan72_minimum_trade_margin": 0.10,
        "plan72_trade_enabled": True,
        **changes,
    }


def test_upgrade_retains_existing_options_and_plan72_starts_disabled(flow_module):
    original = {"energy_need_enabled": True, "energy_need_capacity_entity": "sensor.capacity",
                "energy_need_reserve_percent": 5, "tariff_profile_id": "existing"}
    flow = make_flow(flow_module, original)
    result = run(flow.async_step_init())
    keys = {key.schema: key for key in result["data_schema"].schema}
    assert keys["plan72_enabled"].default() is False
    assert flow._pending == original
    assert run(flow._continue_after_prices())["data"] == original


@pytest.mark.parametrize("missing", ["energy_forecast_enabled", "solar_foundation_enabled",
                                      "prices_enabled", "energy_need_enabled"])
def test_each_dependency_is_required_and_form_retains_plan_choice(flow_module, missing):
    values = {key: True for key in ("plan72_enabled", "energy_forecast_enabled",
                                    "solar_foundation_enabled", "prices_enabled", "energy_need_enabled")}
    values[missing] = False
    result = run(make_flow(flow_module).async_step_init(values))
    assert result["errors"] == {"base": "plan72_requires_sources"}
    keys = {key.schema: key for key in result["data_schema"].schema}
    assert keys["plan72_enabled"].default() is True
    assert keys[missing].default() is False


def test_power_limits_have_no_guessed_defaults(flow_module):
    result = run(make_flow(flow_module).async_step_plan72())
    keys = {key.schema: key for key in result["data_schema"].schema}
    assert keys["plan72_max_charge_power_w"].default is vol.UNDEFINED
    assert keys["plan72_max_discharge_power_w"].default is vol.UNDEFINED
    assert keys["plan72_minimum_trade_margin"].default() == 0.10


@pytest.mark.parametrize("value", [None, 0, -1, True, "unknown", float("nan"), float("inf")])
def test_invalid_power_is_rejected_without_saving(flow_module, value):
    flow = make_flow(flow_module, {"energy_need_reserve_percent": 5})
    result = run(flow.async_step_plan72(valid_plan_input(plan72_max_charge_power_w=value)))
    assert result["type"] == "form"
    assert result["errors"]["plan72_max_charge_power_w"] == "invalid_plan72_value"
    assert flow._pending == {"energy_need_reserve_percent": 5}


def test_finish_prices_opens_plan72_and_preserves_all_existing_options(flow_module):
    original = {"plan72_enabled": True, "energy_need_reserve_percent": 5,
                "energy_need_capacity_entity": "sensor.capacity", "solar_arrays": [{"array_id": "unchanged"}]}
    flow = make_flow(flow_module, original)
    assert run(flow._continue_after_prices())["step_id"] == "plan72"
    result = run(flow.async_step_plan72(valid_plan_input()))
    assert result["type"] == "create_entry"
    for key, value in original.items():
        assert result["data"][key] == value
    assert result["data"]["plan72_max_charge_power_w"] == 3200.0
    assert result["data"]["plan72_trade_enabled"] is True


def test_plan72_option_labels_are_available_in_both_languages():
    for name in ("strings.json", "translations/en.json", "translations/nl.json"):
        data = json.loads((ROOT / "custom_components/doems" / name).read_text())
        assert "plan72_enabled" in data["options"]["step"]["init"]["data"]
        assert set(valid_plan_input()) <= data["options"]["step"]["plan72"]["data"].keys()
        assert "plan72_requires_sources" in data["options"]["error"]
