"""Adapter safety tests: never actuate without explicit authority."""
from types import SimpleNamespace
import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.doems.execution_anker_adapter import AnkerExecutionAdapter


class FakeServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, *args, **kwargs):
        self.calls.append((args, kwargs))


@pytest.mark.asyncio
async def test_start_denied_without_authority():
    services = FakeServices()
    hass = SimpleNamespace(services=services, states=SimpleNamespace(get=lambda _: None))
    adapter = AnkerExecutionAdapter(hass, {
        "operating_mode": "select.mode",
        "action_direction": "select.direction",
        "power_setpoint": "number.power",
    })
    with pytest.raises(HomeAssistantError, match="not authorized"):
        await adapter.start(action="laden", power_w=500, revalidate=lambda: True)
    assert not services.calls


@pytest.mark.asyncio
async def test_safe_return_denied_without_authority():
    services = FakeServices()
    hass = SimpleNamespace(services=services, states=SimpleNamespace(get=lambda _: None))
    adapter = AnkerExecutionAdapter(hass, {})
    with pytest.raises(HomeAssistantError, match="not authorized"):
        await adapter.safe_return()
    assert not services.calls


@pytest.mark.asyncio
async def test_invalid_action_denied_even_with_authority():
    services = FakeServices()
    hass = SimpleNamespace(services=services, states=SimpleNamespace(get=lambda _: None))
    adapter = AnkerExecutionAdapter(hass, {}, authority=True)
    with pytest.raises(HomeAssistantError, match="Invalid action"):
        await adapter.start(action="export", power_w=500, revalidate=lambda: True)
    assert not services.calls
