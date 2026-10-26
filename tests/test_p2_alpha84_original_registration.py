"""P2 original Alpha84 live instance registration; no physical calls."""
from types import SimpleNamespace
import pytest

from custom_components.doems.alpha84_original_registration import (
    OriginalAlpha84Registration, OriginalControllerUnavailable,
)


def loaded():
    coordinator = SimpleNamespace(
        authority_fence=object(), plan_store=object(),
        control_entity_ids=lambda: {}, async_refresh=lambda: None, data={},
    )
    coordinator.physical_test = SimpleNamespace(_coordinator=coordinator)
    controller = SimpleNamespace(
        _coordinator=coordinator, entry_id="existing-entry",
        evaluate_final_revalidation=lambda data: {"safe": False},
    )
    coordinator.execution = controller
    hass = SimpleNamespace(data={"anker_ems": {"existing-entry": coordinator}})
    return hass, coordinator, controller


def test_registers_original_controller_and_coordinator_without_instantiation():
    hass, coordinator, controller = loaded()
    binding = OriginalAlpha84Registration(hass)
    result = binding.register()
    assert result["status"] == "registered_read_only"
    assert result["physical_execution_enabled"] is False
    assert binding.verified_controller() is controller
    assert binding.coordinator is coordinator


def test_missing_original_integration_fails_closed():
    binding = OriginalAlpha84Registration(SimpleNamespace(data={}))
    with pytest.raises(OriginalControllerUnavailable):
        binding.register()


def test_ambiguous_original_integration_fails_closed():
    hass, coordinator, _ = loaded()
    hass.data["anker_ems"]["second"] = coordinator
    with pytest.raises(OriginalControllerUnavailable):
        OriginalAlpha84Registration(hass).register()


def test_detached_original_controller_fails_closed():
    hass, coordinator, controller = loaded()
    controller._coordinator = object()
    with pytest.raises(OriginalControllerUnavailable, match="not attached"):
        OriginalAlpha84Registration(hass).register()


def test_original_unload_invalidates_binding():
    hass, _, _ = loaded()
    binding = OriginalAlpha84Registration(hass)
    binding.register()
    hass.data["anker_ems"].clear()
    with pytest.raises(OriginalControllerUnavailable):
        binding.verified_controller()


def test_replaced_original_controller_invalidates_binding():
    hass, coordinator, _ = loaded()
    binding = OriginalAlpha84Registration(hass)
    binding.register()
    coordinator.execution = object()
    with pytest.raises(OriginalControllerUnavailable):
        binding.verified_controller()
