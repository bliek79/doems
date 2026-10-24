"""Behavioral Combined -> controller -> Anker service tests. No real devices."""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def chain(monkeypatch):
    package = ModuleType('recovery_battery_test')
    package.__path__ = [str(Path(__file__).resolve().parents[1] / 'custom_components/doems')]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    modules = {}
    for name in ('execution_watchdog', 'execution_control_path', 'execution_anker_adapter', 'execution_controller', 'combined_execution_shadow', 'combined_anker_bridge'):
        fullname = f'{package.__name__}.{name}'
        monkeypatch.delitem(sys.modules, fullname, raising=False)
        modules[name] = importlib.import_module(fullname)
    clock = SimpleNamespace(now=datetime(2026, 10, 24, 12, 1, tzinfo=timezone.utc))
    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now.astimezone(tz) if tz else clock.now.replace(tzinfo=None)
    monkeypatch.setattr(modules['combined_anker_bridge'], 'datetime', ClockDateTime)
    adapter_module = modules['execution_anker_adapter']
    monkeypatch.setattr(adapter_module.dt_util, 'utcnow', lambda: clock.now)
    async def sleep(seconds):
        clock.now += timedelta(seconds=seconds)
    monkeypatch.setattr(adapter_module.asyncio, 'sleep', sleep)
    entities = {'operating_mode': 'select.test_mode', 'action_direction': 'select.test_direction', 'power_setpoint': 'number.test_power'}
    states = {}
    def set_state(key, value):
        states[entities[key]] = SimpleNamespace(state=str(value), last_changed=clock.now)
    for key, value in [('operating_mode', 'self_consumption'), ('action_direction', 'charge'), ('power_setpoint', 0)]:
        set_state(key, value)
        states[entities[key]].last_changed -= timedelta(seconds=120)
    calls = []
    fail = SimpleNamespace(nonzero=False, stop=False, no_ack=False)
    async def call(domain, service, data, *, target, blocking):
        calls.append((domain, service, dict(data), dict(target)))
        entity = target['entity_id']
        if domain == 'number':
            if fail.nonzero and data['value'] != 0:
                raise RuntimeError('simulated command rejection')
            if fail.stop and data['value'] == 0:
                raise RuntimeError('simulated stop rejection')
            if fail.no_ack and data['value'] != 0:
                return
            set_state('power_setpoint', data['value'])
        else:
            set_state('operating_mode' if entity == entities['operating_mode'] else 'action_direction', data['option'])
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get), services=SimpleNamespace(async_call=call))
    adapter = adapter_module.AnkerExecutionAdapter(hass, entities, authority=True)
    start = clock.now.replace(minute=0, second=0, microsecond=0)
    snapshot = {'valid': True, 'blockers': [], 'native_slots': [
        {'start': (start + timedelta(minutes=i*15)).isoformat(),
         'end': (start + timedelta(minutes=(i+1)*15)).isoformat(),
         'manual_charge_kwh': 0.25 if i == 0 else 0,
         'manual_discharge_kwh': 0, 'charge_from_grid_safety_kwh': 0,
         'charge_from_grid_trade_kwh': 0, 'discharge_to_grid_kwh': 0,
         'automatic_floor_soc_percent': 10} for i in range(288)]}
    battery = {'status': 'ready', 'soc_percent': 50, 'sources_fresh': True}
    bridge_ref = {}
    controller = modules['execution_controller'].ExecutionController(
        adapter, authorized=lambda: bridge_ref['bridge']._authorized(),
        revalidate=lambda identity: bridge_ref['bridge']._still_current(identity))
    bridge = modules['combined_anker_bridge'].CombinedAnkerBridge(
        SimpleNamespace(snapshot=lambda kind: snapshot if kind == 'combined' else pytest.fail('non Combined source')),
        adapter, battery=SimpleNamespace(snapshot=lambda: battery), authority=True,
        exclusive=True, controller=controller)
    bridge_ref['bridge'] = bridge
    return SimpleNamespace(bridge=bridge, controller=controller, adapter=adapter,
        clock=clock, snapshot=snapshot, battery=battery, calls=calls, states=states,
        fail=fail, set_state=set_state)


@pytest.mark.parametrize('action', ['charge', 'discharge'])
def test_combined_start_verified_readback_and_shutdown(chain, action):
    async def run():
        slot = chain.snapshot['native_slots'][0]
        slot['manual_charge_kwh'] = 0.25 if action == 'charge' else 0
        slot['manual_discharge_kwh'] = 0.25 if action == 'discharge' else 0
        before = chain.clock.now
        result = await chain.bridge.async_reconcile(chain.clock.now)
        assert result['bridge'] == 'running'
        assert chain.adapter._state('action_direction') == action
        assert chain.adapter._power_matches(1000)
        assert (chain.clock.now - before).total_seconds() >= 60
        assert len([c for c in chain.calls if c[0] == 'number' and c[2]['value'] > 0]) == 1
        await chain.bridge.async_reconcile(chain.clock.now)
        assert len([c for c in chain.calls if c[0] == 'number' and c[2]['value'] > 0]) == 1
        await chain.bridge.async_shutdown()
        assert chain.controller.session is None
        assert chain.adapter._power_zero()
        assert chain.adapter._state('operating_mode') == 'self_consumption'
    asyncio.run(run())


@pytest.mark.parametrize('guard', ['authority', 'exclusive', 'soc', 'reserve', 'planner', 'power'])
def test_start_guards_emit_no_nonzero_command(chain, guard):
    if guard == 'authority': chain.bridge.authority = False
    if guard == 'exclusive': chain.bridge.exclusive = False
    if guard == 'soc': chain.battery['soc_percent'] = None
    if guard == 'reserve':
        slot = chain.snapshot['native_slots'][0]
        slot['manual_charge_kwh'] = 0
        slot['manual_discharge_kwh'] = 0.25
        chain.battery['soc_percent'] = 10
    if guard == 'planner': chain.snapshot['valid'] = False
    if guard == 'power': chain.snapshot['native_slots'][0]['manual_charge_kwh'] = 1
    asyncio.run(chain.bridge.async_reconcile(chain.clock.now))
    assert not chain.calls
    assert chain.controller.session is None


@pytest.mark.parametrize('fault', ['nonzero', 'no_ack'])
def test_rejected_command_or_missing_readback_returns_to_self(chain, fault):
    async def run():
        setattr(chain.fail, fault, True)
        with pytest.raises(Exception):
            await chain.bridge.async_reconcile(chain.clock.now)
        assert chain.controller.reconciliation_required
        assert chain.adapter._power_zero()
        assert chain.adapter._state('operating_mode') == 'self_consumption'
    asyncio.run(run())


def test_restart_in_external_mode_reconciles_before_any_start(chain):
    chain.set_state('operating_mode', 'third_party_control')
    chain.set_state('power_setpoint', 1000)
    result = asyncio.run(chain.bridge.async_reconcile(chain.clock.now))
    assert result['bridge'] == 'startup_reconciled'
    assert chain.adapter._power_zero()
    assert chain.adapter._state('operating_mode') == 'self_consumption'
    assert not any(c[0] == 'number' and c[2]['value'] > 0 for c in chain.calls)


@pytest.mark.parametrize('fault', ['quarter', 'revision', 'soc', 'authority', 'readback'])
def test_running_session_stops_on_watchdog_fault(chain, fault):
    async def run():
        await chain.bridge.async_reconcile(chain.clock.now)
        if fault == 'quarter': chain.clock.now = chain.clock.now.replace(minute=15, second=0)
        if fault == 'revision': chain.snapshot['native_slots'][0]['manual_charge_kwh'] = 0.5
        if fault == 'soc': chain.battery['soc_percent'] = None
        if fault == 'authority': chain.bridge.authority = False
        if fault == 'readback': chain.set_state('power_setpoint', 9999)
        await chain.bridge.async_reconcile(chain.clock.now)
        assert chain.controller.session is None
        assert chain.adapter._power_zero()
        assert chain.adapter._state('operating_mode') == 'self_consumption'
    asyncio.run(run())


def test_stop_failure_keeps_reconciliation_fence(chain):
    async def run():
        await chain.bridge.async_reconcile(chain.clock.now)
        chain.fail.stop = True
        with pytest.raises(Exception): await chain.bridge.async_shutdown()
        assert chain.controller.reconciliation_required
        assert chain.controller.session is not None
    asyncio.run(run())
