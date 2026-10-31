"""Execute the actual durable store; no source-text assertions or battery access."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys
import types

import pytest


@pytest.fixture
def store_module(monkeypatch):
    def module(name, **members):
        item = types.ModuleType(name)
        item.__path__ = []
        item.__dict__.update(members)
        monkeypatch.setitem(sys.modules, name, item)
        return item
    class Storage:
        data = None
        fail = False
        def __init__(self, *args): pass
        def __class_getitem__(cls, item): return cls
        async def async_load(self): return deepcopy(self.data)
        async def async_save(self, value):
            await asyncio.sleep(0)
            if self.fail: raise OSError('disk_failure')
            self.data = deepcopy(value)
    module('homeassistant')
    def callback(fn):
        fn._hass_callback = True
        return fn
    module('homeassistant.core', HomeAssistant=object, callback=callback)
    from enum import StrEnum
    class EntityCategory(StrEnum):
        DIAGNOSTIC = 'diagnostic'
    module('homeassistant.const', EntityCategory=EntityCategory)
    module('homeassistant.helpers')
    module('homeassistant.helpers.storage', Store=Storage)
    module("homeassistant.helpers.event", async_track_time_interval=lambda *a, **kw: lambda: None)
    dt = module('homeassistant.util.dt', now=lambda: datetime(2026, 10, 30, 12, tzinfo=timezone.utc),
                parse_datetime=lambda x: datetime.fromisoformat(x), DEFAULT_TIME_ZONE=timezone.utc, utcnow=lambda: datetime(2026, 10, 30, 12, tzinfo=timezone.utc))
    module('homeassistant.util', dt=dt)
    package = module('store_ch7_test')
    package.__path__ = [str(Path(__file__).resolve().parents[1] / 'custom_components/doems')]
    imported = importlib.import_module('store_ch7_test.plan_store')
    yield imported
    for name in list(sys.modules):
        if name.startswith('store_ch7_test.'):
            sys.modules.pop(name, None)


def proposal(identity='a'):
    return dict(action='laden', execution_mode='gepland', power_w=1000, target_soc=80,
                max_runtime_h=.25, max_start_delay_min=0,
                start_time='2026-10-31T12:00:00+00:00', planner_identity=identity,
                planner_signature=identity, planned_energy_kwh=.25,
                source_plan_generation=1, source_input_fingerprint='f')


def test_empty_slots_really_fill_and_restore(store_module):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        result = await store.async_sync_automatic_plans({1: proposal()})
        assert result['written_slots'] == [1]
        assert store.revision == 1
        restored = store_module.AnkerEmsPlanStore(None, 'id')
        restored._store.data = store._store.data
        await restored.async_load()
        assert restored.revision == 1
        assert restored.get_plan(1) == store.get_plan(1)
        assert not (await store.async_sync_automatic_plans({1: proposal()}))['changed']
        assert store.revision == 1
    asyncio.run(run())


def test_manual_claim_blocks_stale_writer_and_survives_failure(store_module):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        await store.async_set_value(1, 'action', 'laden')
        with pytest.raises(ValueError, match='stale_store_revision'):
            await store.async_sync_automatic_plans({1: proposal()}, expected_revision=0)
        assert store.get_plan(1)['origin'] == 'manual'
        assert (await store.async_sync_automatic_plans({1: proposal()}))['skipped_slots'] == [1]
        before = store.get_plan(1)
        store._store.fail = True
        with pytest.raises(OSError):
            await store.async_set_value(1, 'power_w', 2000)
        assert store.get_plan(1) == before
        assert store.revision == 1
    asyncio.run(run())


def test_waiting_writer_checks_source_inside_lock(store_module):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        await store._lock.acquire()
        current = True
        task = asyncio.create_task(store.async_sync_automatic_plans(
            {1: proposal()}, expected_revision=0, source_is_current=lambda: current))
        await asyncio.sleep(0)
        current = False
        store._lock.release()
        with pytest.raises(ValueError, match='superseded_source'): await task
        assert store.revision == 0
        assert store.get_plan(1)['action'] == 'geen'
    asyncio.run(run())


def test_real_writer_fills_three_slots_reports_overflow_and_honors_manual(store_module):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        writer_module = importlib.import_module('store_ch7_test.plan_store_writer')
        source = types.SimpleNamespace(snapshot=dict(valid=True, start="2026-10-30T12:00:00+00:00", plan_generation=1, input_fingerprint='f'))
        candidates = []
        for identity in ('a', 'b', 'c', 'd'):
            item = proposal(identity)
            item.update(action='charge', valid=True, selection_status='eligible',
                        power_start_time='2026-10-31T12:02:00+00:00',
                        planned_end_time='2026-10-31T12:15:00+00:00',
                        command_target_soc=80, projected_end_soc=65)
            candidates.append(item)
        bridge = types.SimpleNamespace(snapshot=dict(valid=True, status='ready',
            source_plan_generation=1, source_input_fingerprint='f', eligible_candidates=candidates))
        writer = writer_module.PlanStoreWriter(None, store, source, bridge)
        await writer._sync()
        assert writer.status == 'ready'
        assert writer.diagnostics['overflow'] == 1
        assert [store.get_value(i, 'planner_identity') for i in range(1, 4)] == ['a','b','c']
        assert store.get_value(1, 'planned_end_time') == '2026-10-31T12:15:00+00:00'
        assert store.get_value(1, 'power_start_time') == '2026-10-31T12:02:00+00:00'
        await store.async_set_value(1, 'power_w', 1200)
        # A fresh shared route now represents slot 1 as a manual constraint.
        bridge.snapshot = {**bridge.snapshot, 'eligible_candidates': candidates[1:]}
        await writer._sync()
        assert store.get_value(1, 'origin') == 'manual'
        assert store.get_value(1, 'power_w') == 1200
        assert store.get_value(2, 'planner_identity') == 'b'
        assert store.get_value(3, 'planner_identity') == 'c'
        assert writer.diagnostics['overflow'] == 1
    asyncio.run(run())


def test_due_and_active_slots_survive_reconciliation_and_restart(store_module):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        await store.async_sync_automatic_plans({1: proposal()})
        await store.async_mark_lifecycle(1, 'actief', 'external_lifecycle')
        before = store.get_plan(1)
        assert not (await store.async_sync_automatic_plans({1: proposal('replacement')}))['changed']
        with pytest.raises(ValueError, match='active'):
            await store.async_set_value(1, 'action', 'geen')
        restored = store_module.AnkerEmsPlanStore(None, 'id')
        restored._store.data = store._store.data
        await restored.async_load()
        assert restored.get_plan(1) == before
        assert not (await restored.async_release_expired_automatic_plans())['changed']
    asyncio.run(run())


def test_manual_schedule_cancel_default_delay_and_no_physical_lifecycle(store_module):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        assert store.get_value(1, 'max_start_delay_min') == 5
        with pytest.raises(ValueError, match='manual_action_required'):
            await store.async_schedule_manual_plan(1)
        await store.async_set_value(1, 'action', 'laden')
        await store.async_schedule_manual_plan(1)
        assert store.get_value(1, 'lifecycle_status') == 'pending'
        assert store.get_value(1, 'start_time') == '2026-10-30T12:00:00+00:00'
        await store.async_cancel_plan(1)
        assert store.get_value(1, 'lifecycle_status') == 'geannuleerd'
        await store.async_set_value(1, 'execution_mode', 'gepland')
        await store.async_set_value(1, 'start_time', '2026-10-31T12:00:00+00:00')
        await store.async_schedule_manual_plan(1)
        assert store.plan_status(1) == 'gepland'
    asyncio.run(run())


def test_entities_edit_and_restore_actual_store_and_have_exact_register(store_module, monkeypatch):
    class Entity:
        async def async_added_to_hass(self): pass
        async def async_will_remove_from_hass(self): pass
        def async_write_ha_state(self): pass
    for domain, cls in [('sensor', 'SensorEntity'), ('number', 'NumberEntity'),
                        ('select', 'SelectEntity'), ('datetime', 'DateTimeEntity')]:
        module = types.ModuleType('homeassistant.components.' + domain)
        setattr(module, cls, Entity)
        if domain == 'number': module.NumberMode = types.SimpleNamespace(BOX='box')
        monkeypatch.setitem(sys.modules, module.__name__, module)
    registry = types.ModuleType('homeassistant.helpers.device_registry')
    registry.DeviceInfo = dict
    monkeypatch.setitem(sys.modules, registry.__name__, registry)
    module = importlib.import_module('store_ch7_test.plan_slot_entities')
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        entry = types.SimpleNamespace(entry_id='id')
        entities = []
        for slot in range(1, 4):
            entities += [module.SlotSelect(entry, store, slot, field) for field in module.SELECTS]
            entities += [module.SlotNumber(entry, store, slot, field) for field in module.NUMBERS]
            entities += [module.SlotStart(entry, store, slot, 'start_time'), module.SlotStatus(entry, store, slot, 'status')]
        assert len(entities) == 24
        for entity in entities: await entity.async_added_to_hass()
        assert len(store._listeners) == 24
        await entities[0].async_select_option('laden')
        await entities[2].async_set_native_value(1200)
        await entities[6].async_set_value(datetime(2026,10,31,12,tzinfo=timezone.utc))
        assert entities[0].current_option == 'laden'
        assert entities[2].native_value == 1200
        assert entities[6].native_value.day == 31
        assert entities[7].native_value == 'concept'
        for entity in entities: await entity.async_will_remove_from_hass()
        assert not store._listeners
        rows = module.entity_register('id')
        assert len(rows) == len(set(x[0] for x in rows)) == len(set(x[1] for x in rows)) == 30
        assert rows[0] == ('select.doems_slot_1_action', 'id_slot_1_action')
        assert rows[-1] == ('sensor.doems_plan_store_overflow', 'id_plan_store_overflow')
        from homeassistant.const import EntityCategory
        for field in module.DIAGNOSTICS:
            diagnostic = module.StoreDiagnostic(entry, store, None, field)
            assert isinstance(diagnostic._attr_entity_category, EntityCategory)
    asyncio.run(run())


def test_writer_refuses_mismatched_generation_without_clearing_slots(store_module):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        await store.async_sync_automatic_plans({1: proposal()})
        before = store.get_plan(1)
        module = importlib.import_module('store_ch7_test.plan_store_writer')
        source = types.SimpleNamespace(snapshot=dict(valid=True, start="2026-10-30T12:00:00+00:00", plan_generation=2, input_fingerprint='new'))
        bridge = types.SimpleNamespace(snapshot=dict(valid=True, source_plan_generation=1, source_input_fingerprint='old'))
        writer = module.PlanStoreWriter(None, store, source, bridge)
        await writer._sync()
        assert writer.status == 'blocked'
        assert store.get_plan(1) == before
    asyncio.run(run())


def test_readers_only_see_committed_plan_while_save_is_pending(store_module):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        gate = asyncio.Event()
        original = store._store.async_save
        async def save(value):
            await gate.wait()
            await original(value)
        store._store.async_save = save
        task = asyncio.create_task(store.async_set_value(1, 'action', 'laden'))
        await asyncio.sleep(0)
        assert store.get_value(1, 'action') == 'geen'
        gate.set()
        await task
        assert store.get_value(1, 'action') == 'laden'
    asyncio.run(run())


def test_manual_five_minute_expiry_releases_slot_and_retains_reason(store_module, monkeypatch):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        await store.async_set_value(1, 'action', 'laden')
        await store.async_set_value(1, 'execution_mode', 'gepland')
        await store.async_set_value(1, 'start_time', '2026-10-30T11:55:00+00:00')
        await store.async_mark_lifecycle(1, 'pending')
        await store.async_expire_manual_plans()
        assert store.get_value(1, 'lifecycle_status') == 'pending'
        monkeypatch.setattr(store_module.dt_util, 'now', lambda: datetime(2026,10,30,12,0,1,tzinfo=timezone.utc))
        await store.async_expire_manual_plans()
        assert store.get_value(1, 'action') == 'geen'
        assert store.last_closed_plan(1)['reason'] == 'manual_start_window_expired'
        assert (await store.async_sync_automatic_plans({1: proposal()}))['written_slots'] == [1]
        assert store.last_closed_plan(1)['plan']['action'] == 'laden'
    asyncio.run(run())


def test_overflow_rolls_into_expired_slot_with_survivors_unchanged(store_module, monkeypatch):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        module = importlib.import_module('store_ch7_test.plan_store_writer')
        clock = types.SimpleNamespace(now=datetime(2026,10,30,12,tzinfo=timezone.utc))
        monkeypatch.setattr(store_module.dt_util, 'now', lambda: clock.now)
        monkeypatch.setattr(store_module.dt_util, 'utcnow', lambda: clock.now)
        candidates = []
        for identity, minute in [('a',15), ('b',30), ('c',45), ('d',60)]:
            from datetime import timedelta
            start = clock.now + timedelta(minutes=minute)
            item = proposal(identity)
            item.update(action='charge', valid=True, selection_status='eligible',
                        start_time=start.isoformat(), power_start_time=(start+timedelta(minutes=2)).isoformat(),
                        planned_end_time=(start+timedelta(minutes=15)).isoformat(),
                        command_target_soc=80, projected_end_soc=65)
            candidates.append(item)
        source = types.SimpleNamespace(snapshot=dict(valid=True, start=clock.now.isoformat(), plan_generation=1, input_fingerprint='f'))
        bridge = types.SimpleNamespace(snapshot=dict(valid=True,status='ready',source_plan_generation=1,
            source_input_fingerprint='f',eligible_candidates=candidates))
        writer = module.PlanStoreWriter(None, store, source, bridge)
        await writer._sync()
        survivors = [store.get_plan(i) for i in (2,3)]
        assert writer.diagnostics['overflow'] == 1
        clock.now += timedelta(minutes=16)
        source.snapshot = {**source.snapshot, 'start':'2026-10-30T12:30:00+00:00'}
        await writer._sync()
        assert store.get_value(1, 'planner_identity') == 'd'
        assert [store.get_plan(i) for i in (2,3)] == survivors
        assert writer.diagnostics['overflow'] == 0
    asyncio.run(run())


def test_timer_is_registered_as_event_loop_callback(store_module, monkeypatch):
    async def run():
        module = importlib.import_module('store_ch7_test.plan_store_writer')
        registered = []
        def track(hass, action, interval):
            assert getattr(action, '_hass_callback', False), 'HA would run unmarked sync timer in executor'
            registered.append(action)
            return lambda: None
        monkeypatch.setattr(module, 'async_track_time_interval', track)
        store = store_module.AnkerEmsPlanStore(None, 'id')
        class Hass:
            def async_create_task(self, coro): return asyncio.create_task(coro)
        bridge = types.SimpleNamespace(async_add_listener=lambda fn: lambda: None)
        writer = module.PlanStoreWriter(Hass(), store, None, bridge)
        calls = []
        async def sync(): calls.append('event-loop')
        monkeypatch.setattr(writer, '_sync', sync)
        await writer.async_setup()
        await writer._task
        registered[0](None)
        await writer._task
        assert calls == ['event-loop', 'event-loop']
        await writer.async_shutdown()
    asyncio.run(run())


def test_old_expired_fault_is_released_with_history_surviving_restart(store_module):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        raw = dict(store_module.DEFAULT_PLAN, action='ontladen', execution_mode='gepland',
                   start_time='2026-10-06T17:00:00+00:00', lifecycle_status='fout',
                   lifecycle_reason='manual_start_window_expired',
                   planned_end_time='2026-10-05T23:15:00+00:00', power_w=2500)
        store._store.data = {'plans': {'3': raw}, 'revision': 253}
        await store.async_load()
        await store.async_expire_manual_plans()
        assert store.get_value(3, 'action') == 'geen'
        assert store.get_value(3, 'planned_end_time') is None
        assert store.revision == 254
        history = store.last_closed_plan(3)
        assert history['plan'] == raw
        await store.async_sync_automatic_plans({3: proposal()})
        restored = store_module.AnkerEmsPlanStore(None, 'id')
        restored._store.data = store._store.data
        await restored.async_load()
        assert restored.get_value(3, 'origin') == 'automatic_72h_planner'
        assert restored.last_closed_plan(3) == history
    asyncio.run(run())


def test_expiry_preserves_future_active_and_other_faults(store_module):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        for i, status in [(1, 'pending'), (2, 'actief'), (3, 'fout')]:
            await store.async_set_value(i, 'action', 'laden')
            await store.async_set_value(i, 'execution_mode', 'gepland')
            await store.async_set_value(i, 'start_time', '2026-10-31T12:00:00+00:00' if i == 1 else '2026-10-06T12:00:00+00:00')
            await store.async_mark_lifecycle(i, status, 'other_reason')
        before = [store.get_plan(i) for i in range(1,4)]
        await store.async_expire_manual_plans()
        assert [store.get_plan(i) for i in range(1,4)] == before
    asyncio.run(run())


def test_expiry_storage_failure_restores_plan_and_history(store_module):
    async def run():
        store = store_module.AnkerEmsPlanStore(None, 'id')
        await store.async_set_value(1, 'action', 'laden')
        await store.async_set_value(1, 'start_time', '2026-10-06T12:00:00+00:00')
        await store.async_mark_lifecycle(1, 'pending')
        before = store.get_plan(1)
        revision = store.revision
        store._store.fail = True
        with pytest.raises(OSError): await store.async_expire_manual_plans()
        assert store.get_plan(1) == before
        assert store.last_closed_plan(1) is None
        assert store.revision == revision
    asyncio.run(run())
