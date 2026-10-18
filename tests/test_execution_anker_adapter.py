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


@pytest.mark.asyncio
async def test_failed_start_requires_confirmed_safe_return(monkeypatch):
    """A failed mode switch must not be reported as safely recovered without readback."""
    services = FakeServices()
    state = {
        "select.mode": "Self-consumption",
        "select.direction": "charge",
        "number.power": "0",
    }
    hass = SimpleNamespace(
        services=services,
        states=SimpleNamespace(get=lambda entity: SimpleNamespace(state=state[entity])),
    )
    adapter = AnkerExecutionAdapter(hass, {
        "operating_mode": "select.mode",
        "action_direction": "select.direction",
        "power_setpoint": "number.power",
    }, authority=True)

    async def fake_call(domain, service, entity, data):
        if entity == "operating_mode" and data.get("option") != "Self-consumption":
            raise HomeAssistantError("mode switch failed")
        # Deliberately do not update power readback: a command is not an acknowledgement.

    async def fake_wait(predicate, timeout=45):
        if not predicate():
            raise HomeAssistantError("Battery control acknowledgement timeout")

    monkeypatch.setattr(adapter, "_call", fake_call)
    monkeypatch.setattr(adapter, "_wait", fake_wait)
    state["number.power"] = "400"
    with pytest.raises(HomeAssistantError, match="safe return also failed"):
        await adapter.start(action="laden", power_w=500, revalidate=lambda: True)


@pytest.mark.parametrize("readback", ["nan", "inf", "-inf", "unavailable", "not-a-number"])
def test_setpoint_ack_rejects_nonfinite_and_invalid_values(readback):
    hass = SimpleNamespace(
        services=FakeServices(),
        states=SimpleNamespace(get=lambda _: SimpleNamespace(state=readback)),
    )
    adapter = AnkerExecutionAdapter(hass, {"power_setpoint": "number.power"})
    assert adapter._power_matches(500) is False
    assert adapter._power_zero() is False


def test_setpoint_ack_requires_matching_numeric_value():
    hass = SimpleNamespace(
        services=FakeServices(),
        states=SimpleNamespace(get=lambda _: SimpleNamespace(state="499.5")),
    )
    adapter = AnkerExecutionAdapter(hass, {"power_setpoint": "number.power"})
    assert adapter._power_matches(500) is True
    assert adapter._power_matches(450) is False


@pytest.mark.asyncio
async def test_safe_return_requires_power_readback():
    services = FakeServices()
    def get_state(entity):
        if entity == 'select.mode':
            return SimpleNamespace(state='self_consumption')
        return None
    hass = SimpleNamespace(services=services, states=SimpleNamespace(get=get_state))
    adapter = AnkerExecutionAdapter(hass, {'operating_mode': 'select.mode', 'power_setpoint': 'number.power'}, authority=True)
    with pytest.raises(HomeAssistantError, match='power readback unavailable'):
        await adapter.safe_return()


@pytest.mark.asyncio
async def test_stop_denied_without_authority():
    services = FakeServices()
    hass = SimpleNamespace(services=services, states=SimpleNamespace(get=lambda _: None))
    adapter = AnkerExecutionAdapter(hass, {})
    with pytest.raises(HomeAssistantError, match='not authorized'):
        await adapter.stop()
    assert not services.calls


@pytest.mark.asyncio
async def test_start_rejects_unavailable_operating_mode():
    services = FakeServices()
    hass = SimpleNamespace(services=services, states=SimpleNamespace(get=lambda _: None))
    adapter = AnkerExecutionAdapter(hass, {'operating_mode': 'select.mode'}, authority=True)
    with pytest.raises(HomeAssistantError, match='Operating mode unavailable'):
        await adapter.start(action='laden', power_w=500, revalidate=lambda: True)
    assert not services.calls


@pytest.mark.asyncio
async def test_start_requires_power_setpoint_before_mode_switch():
    services = FakeServices()
    def state(entity):
        return SimpleNamespace(state='self_consumption') if entity == 'select.mode' else None
    hass = SimpleNamespace(services=services, states=SimpleNamespace(get=state))
    adapter = AnkerExecutionAdapter(hass, {'operating_mode': 'select.mode', 'power_setpoint': 'number.power'}, authority=True)
    with pytest.raises(HomeAssistantError, match='Power setpoint unavailable'):
        await adapter.start(action='laden', power_w=500, revalidate=lambda: True)
    assert not services.calls
