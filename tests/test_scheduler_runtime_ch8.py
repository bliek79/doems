"""Run real chapter-7 storage and chapter-8 callbacks, including real Plan72."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import importlib
import types
import sys

import pytest

from test_plan_store_persistence_ch7 import store_module
from test_scheduler_ch8 import NOW, plan, automatic
from test_plan72_runtime import environment, setup_runtime, finish


def prepare(store_module, monkeypatch):
    clock=types.SimpleNamespace(now=NOW)
    monkeypatch.setattr(store_module.dt_util,'now',lambda:clock.now)
    monkeypatch.setattr(store_module.dt_util,'utcnow',lambda:clock.now)
    events=importlib.import_module('homeassistant.helpers.event')
    trackers=[]
    def track(*args,**kwargs):
        record={'args':args,'active':True};trackers.append(record)
        def remove(): record['active']=False
        return remove
    monkeypatch.setattr(events,'async_track_point_in_utc_time',track,raising=False)
    monkeypatch.setattr(events,'async_track_time_interval',track)
    def forbidden(*a,**kw):raise AssertionError('physical call forbidden')
    hass=types.SimpleNamespace(async_create_task=asyncio.create_task,
        services=types.SimpleNamespace(async_call=forbidden))
    entry=types.SimpleNamespace(entry_id='entry-a',options={'plan72_max_charge_power_w':3200,'plan72_max_discharge_power_w':3200})
    class Source:
        def __init__(self,snapshot):self.snapshot=snapshot;self.listeners=[]
        def async_add_listener(self,fn):
            self.listeners.append(fn)
            return lambda:self.listeners.remove(fn)
        def emit(self):
            for fn in tuple(self.listeners):fn()
    source=Source(dict(valid=True,status='ready',plan_generation=1,input_fingerprint='fingerprint-a'))
    bridge=Source(dict(valid=True,status='ready',source_plan_generation=1,source_input_fingerprint='fingerprint-a',eligible_candidates=[]))
    module=importlib.import_module(store_module.__package__+'.scheduler_runtime')
    store=store_module.AnkerEmsPlanStore(hass,entry.entry_id)
    return types.SimpleNamespace(clock=clock,trackers=trackers,hass=hass,entry=entry,source=source,
        bridge=bridge,module=module,store=store, runtime=module.SchedulerRuntime(hass,entry,store,source,bridge))


def test_time_callback_uses_actual_time_and_does_not_write_storage(store_module,monkeypatch):
    async def scenario():
        e=prepare(store_module,monkeypatch)
        e.store._plans[1]=automatic()
        e.clock.now=NOW-timedelta(seconds=1)
        await e.runtime.async_setup()
        assert e.runtime.snapshot['scheduler_status']=='wachtend'
        assert any(t['args'][-1]==NOW for t in e.trackers)
        e.clock.now=NOW;e.runtime._tick(NOW)
        assert e.runtime.snapshot['scheduler_ready']
        e.clock.now=NOW+timedelta(microseconds=1);e.runtime._tick(NOW)
        assert e.runtime.snapshot['scheduler_slots'][1]['reason']=='start_window_expired'
        assert e.store.revision==0 and e.store.get_plan(1)['lifecycle_status']=='pending'
        await e.runtime.async_shutdown()
        assert not any(t['active'] for t in e.trackers)
        assert not e.source.listeners and not e.bridge.listeners and not e.store._listeners
        old=e.runtime.snapshot;e.runtime._tick(NOW);e.runtime.schedule()
        assert e.runtime.snapshot is old
    asyncio.run(scenario())


def test_cancel_transaction_failure_restart_and_manual_priority(store_module,monkeypatch):
    async def scenario():
        e=prepare(store_module,monkeypatch)
        await e.store.async_set_value(1,'action','laden')
        await e.store.async_schedule_manual_plan(1)
        await e.runtime.async_setup()
        assert e.runtime.snapshot['scheduler_selected_slot']==1
        before=e.store.revision
        e.store._store.fail=True
        with pytest.raises(OSError):await e.store.async_cancel_plan(1)
        await asyncio.sleep(0)
        assert e.store.revision==before and e.runtime.snapshot['scheduler_selected_slot']==1
        e.store._store.fail=False
        await e.store.async_cancel_plan(1);await asyncio.sleep(0)
        assert e.runtime.snapshot['scheduler_selected_slot'] is None
        assert e.runtime.snapshot['storage_revision']==e.store.revision
        await e.store.async_schedule_manual_plan(1);await asyncio.sleep(0)
        original=e.store.get_plan(1)
        restored=store_module.AnkerEmsPlanStore(e.hass,e.entry.entry_id)
        restored._store.data=deepcopy(e.store._store.data);await restored.async_load()
        await e.runtime.async_shutdown()
        runtime=e.module.SchedulerRuntime(e.hass,e.entry,restored,e.source,e.bridge)
        await runtime.async_setup()
        assert runtime.snapshot['scheduler_selected_slot']==1
        assert restored.get_plan(1)==original
        # Automatic synchronization cannot take the manual slot away.
        result=await restored.async_sync_automatic_plans({1:automatic()})
        assert result['skipped_slots']==[1] and restored.get_plan(1)==original
        await runtime.async_shutdown()
    asyncio.run(scenario())


@pytest.mark.parametrize('mutation,reason', [({'valid':False,'status':'calculating'},'source_not_ready'),
    ({'plan_generation':2},'source_generation_or_fingerprint_mismatch'),
    ({'input_fingerprint':'changed'},'source_generation_or_fingerprint_mismatch')])
def test_source_invalidation_and_coherent_recovery(store_module,monkeypatch,mutation,reason):
    async def scenario():
        e=prepare(store_module,monkeypatch);e.store._plans[1]=plan()
        await e.runtime.async_setup();assert e.runtime.snapshot['scheduler_ready']
        saved=e.source.snapshot;e.source.snapshot={**saved,**mutation};e.source.emit()
        await asyncio.sleep(0)
        assert e.runtime.snapshot['scheduler_ready']
        assert not e.runtime.snapshot['source_consistent']
        assert e.runtime.snapshot['source_blocker']==reason
        assert e.runtime.snapshot['execution_enabled'] is False
        e.source.snapshot=saved;e.source.emit();await asyncio.sleep(0)
        assert e.runtime.snapshot['scheduler_ready'] and e.store.revision==0
        await e.runtime.async_shutdown()
    asyncio.run(scenario())


def test_protected_identity_survives_new_generation_without_faking_prestart(store_module,monkeypatch):
    async def scenario():
        e=prepare(store_module,monkeypatch);e.store._plans[1]=automatic()
        e.source.snapshot.update(plan_generation=2,input_fingerprint='new')
        e.bridge.snapshot.update(source_plan_generation=2,source_input_fingerprint='new',
            eligible_candidates=[automatic(planner_signature='new-signature')])
        await e.runtime.async_setup()
        detail=e.runtime.snapshot['scheduler_slots'][1]
        assert e.runtime.snapshot['scheduler_selected_slot']==1
        assert detail['current_identity_present'] is True
        assert detail['current_signature_matches'] is False
        assert detail['source_generation_matches'] is False
        assert detail['prestart_revalidation_required'] is True
        assert e.store.get_plan(1)['planner_signature']=='signature-a'
        await e.runtime.async_shutdown()
    asyncio.run(scenario())


@pytest.mark.parametrize('change',['revision','identity','source'])
def test_superseded_snapshot_never_publishes_old_selection(store_module,monkeypatch,change):
    async def scenario():
        e=prepare(store_module,monkeypatch);e.store._plans[1]=plan()
        original=e.module.evaluate
        def mutate(*args,**kwargs):
            result=original(*args,**kwargs)
            if change=='revision':e.store.revision+=1
            elif change=='identity':e.store._plans[1]['planner_identity']='changed'
            else:e.source.snapshot={**e.source.snapshot}
            return result
        monkeypatch.setattr(e.module,'evaluate',mutate)
        await e.runtime.async_setup()
        assert not e.runtime.snapshot['scheduler_ready']
        assert e.runtime.snapshot['scheduler_reason']=='superseded_snapshot'
        await e.runtime.async_shutdown()
    asyncio.run(scenario())


def test_all_four_entities_have_approved_ids_and_listener_lifecycle(store_module,monkeypatch):
    async def scenario():
        e=prepare(store_module,monkeypatch);e.store._plans[1]=plan()
        await e.runtime.async_setup()
        class Entity:
            async def async_added_to_hass(self):pass
            async def async_will_remove_from_hass(self):pass
            def async_write_ha_state(self):pass
        for name,attrs in {
            'homeassistant.components':{},'homeassistant.components.sensor':{'SensorEntity':Entity},
            'homeassistant.components.binary_sensor':{'BinarySensorEntity':Entity},
            'homeassistant.helpers.device_registry':{'DeviceInfo':dict},
        }.items():
            m=types.ModuleType(name);m.__dict__.update(attrs);monkeypatch.setitem(sys.modules,name,m)
        entities=importlib.import_module(store_module.__package__+'.scheduler_entities')
        all_entities=[*entities.build_scheduler_sensors(e.entry,e.runtime),entities.SchedulerReady(e.entry,e.runtime)]
        assert [x._attr_unique_id for x in all_entities]==['entry-a_scheduler_'+s for s in ('status','selected_plan','reason','ready')]
        assert [x._attr_suggested_object_id for x in all_entities]==['doems_scheduler_'+s for s in ('status','selected_plan','reason','ready')]
        assert [x.native_value for x in all_entities[:3]]==['startklaar','slot_1','scheduled_due']
        assert all_entities[-1].is_on
        for entity in all_entities:
            await entity.async_added_to_hass()
            attrs=entity.extra_state_attributes
            assert attrs['physical_execution_authority'] is attrs['execution_enabled'] is False
            attrs['scheduler_slots'].clear()
            assert e.runtime.snapshot['scheduler_slots']
            await entity.async_will_remove_from_hass()
        assert not e.runtime.listeners
        await e.runtime.async_shutdown()
    asyncio.run(scenario())


def test_scheduler_ticks_do_not_recompute_real_plan72(environment,monkeypatch):
    async def scenario():
        plan72,hass=setup_runtime(environment)
        events=importlib.import_module('homeassistant.helpers.event')
        monkeypatch.setattr(events,'async_track_point_in_utc_time',lambda *a,**k:lambda:None,raising=False)
        bridge_module=importlib.import_module(environment.runtime.__package__+'.planner_action_bridge_runtime')
        module=importlib.import_module(environment.runtime.__package__+'.scheduler_runtime')
        class Store:
            revision=0
            def get_plan(self,i):return plan(action='geen',lifecycle_status='concept')
            def add_listener(self,fn):return lambda:None
        bridge=bridge_module.ActionBridgeRuntime(plan72)
        await bridge.async_setup();await plan72.async_setup();await finish(plan72)
        runtime=module.SchedulerRuntime(hass,plan72.entry,Store(),plan72,bridge)
        await runtime.async_setup()
        count=plan72.calculation_count
        for _ in range(100):runtime._tick(environment.clock.now)
        assert plan72.calculation_count==count and not plan72._worker_task
        hass.states.values['sensor.battery_soc'].state='unavailable'
        plan72._battery_changed(None);await asyncio.sleep(0)
        assert runtime.snapshot['source_blocker']=='source_not_ready'
        hass.states.values['sensor.battery_soc'].state='60'
        plan72._battery_changed(None);await finish(plan72);await asyncio.sleep(0)
        assert runtime.snapshot['source_consistent']
        assert plan72.calculation_count==count+1
        await runtime.async_shutdown();await bridge.async_shutdown();await plan72.async_shutdown()
    asyncio.run(scenario())


def test_actual_writer_refill_expiry_and_restored_automatic_slots(store_module,monkeypatch):
    async def scenario():
        e=prepare(store_module,monkeypatch)
        writer_module=importlib.import_module(store_module.__package__+'.plan_store_writer')
        start=NOW+timedelta(minutes=15)
        item=automatic(start_time=start.isoformat(),power_start_time=(start+timedelta(minutes=2)).isoformat(),
            planned_end_time=(start+timedelta(minutes=15)).isoformat(),action='charge',
            valid=True,selection_status='eligible',planned_energy_kwh=.2)
        e.source.snapshot['start']=NOW.isoformat()
        e.bridge.snapshot['eligible_candidates']=[item]
        writer=writer_module.PlanStoreWriter(e.hass,e.store,e.source,e.bridge)
        await writer._sync()
        await e.runtime.async_setup()
        assert e.runtime.snapshot['scheduler_status']=='wachtend'
        identity=e.store.get_plan(1)['planner_identity']
        await e.store.async_cancel_plan(1);await asyncio.sleep(0)
        assert not e.runtime.snapshot['scheduler_ready']
        await writer._sync();await asyncio.sleep(0)
        assert e.store.get_plan(1)['lifecycle_status']=='pending'
        assert e.store.get_plan(1)['planner_identity']==identity
        restored=store_module.AnkerEmsPlanStore(e.hass,e.entry.entry_id)
        restored._store.data=deepcopy(e.store._store.data);await restored.async_load()
        assert restored.get_plan(1)==e.store.get_plan(1)
        await e.runtime.async_shutdown()
        runtime=e.module.SchedulerRuntime(e.hass,e.entry,restored,e.source,e.bridge)
        e.clock.now=start;await runtime.async_setup()
        assert runtime.snapshot['scheduler_selected_slot']==1
        e.clock.now=start+timedelta(minutes=10,microseconds=1);runtime._tick(start)
        assert runtime.snapshot['scheduler_slots'][1]['status']=='verlopen'
        # Only the existing Store performs cleanup, after the read-only diagnosis.
        await restored.async_release_expired_automatic_plans();await asyncio.sleep(0)
        assert runtime.snapshot['scheduler_slots'][1]['status']=='leeg'
        assert restored.get_plan(1)['action']=='geen'
        await runtime.async_shutdown()
    asyncio.run(scenario())


def test_disabled_planning_keeps_diagnostics_and_never_selects(store_module,monkeypatch):
    async def scenario():
        e=prepare(store_module,monkeypatch);e.store._plans[1]=plan()
        runtime=e.module.SchedulerRuntime(e.hass,e.entry,e.store,None,None)
        await runtime.async_setup()
        assert runtime.snapshot['source_blocker']=='planning_not_enabled'
        assert runtime.snapshot['scheduler_ready']
        assert runtime.snapshot['execution_enabled'] is False
        await runtime.async_shutdown()
    asyncio.run(scenario())
