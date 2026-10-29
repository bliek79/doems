"""Real Plan72 -> Bridge notifications, invalidation, entity lifecycle and isolation."""
import asyncio
import importlib
from pathlib import Path

from test_plan72_runtime import environment, setup_runtime, finish


def test_real_runtime_publishes_same_generation_and_invalidates_without_service_calls(environment):
    async def scenario():
        plan72,hass=setup_runtime(environment)
        module=importlib.import_module(environment.runtime.__package__+'.planner_action_bridge_runtime')
        runtime=module.ActionBridgeRuntime(plan72)
        await runtime.async_setup()
        assert not runtime.snapshot['valid']
        await plan72.async_setup();await finish(plan72)
        assert runtime.snapshot['valid']
        assert runtime.snapshot['status']=='idle'
        assert runtime.snapshot['source_plan_generation']==plan72.snapshot['plan_generation']
        assert runtime.snapshot['source_input_fingerprint']==plan72.snapshot['input_fingerprint']
        assert plan72.snapshot['battery_parameters']['capacity_kwh']=='7.2'
        runtime.plan72.solar.last_error='source_lost';runtime.plan72.solar._notify()
        assert not runtime.snapshot['valid']
        assert runtime.snapshot['candidates']==[]
        assert runtime.snapshot['slot_preview']==[]
        runtime.plan72.solar.last_error=None;runtime.plan72.solar._notify()
        await finish(plan72)
        assert runtime.snapshot['valid']
        sensors=module.build_action_bridge_sensors(runtime)
        valid=module.ActionBridgeValid(runtime)
        entities=[*sensors,valid]
        assert len({x._attr_unique_id for x in entities})==4
        assert valid.is_on is True
        assert [x.native_value for x in sensors]==['idle',0,0]
        for entity in entities:
            await entity.async_added_to_hass()
            attrs=entity.extra_state_attributes
            assert attrs['execution_enabled'] is False
            assert attrs['physical_execution_authority'] is False
            assert attrs['plan_store_write_enabled'] is False
            await entity.async_will_remove_from_hass()
        assert not runtime.listeners
        old=runtime.snapshot
        await runtime.async_shutdown()
        plan72._notify();runtime.refresh()
        assert runtime.snapshot is old
        assert not plan72.listeners
        await plan72.async_shutdown()
    asyncio.run(scenario())


def test_chapter6_has_no_io_storage_or_physical_control_surface():
    root=Path(__file__).resolve().parents[1]/'custom_components/doems'
    for name in ('planner_action_bridge.py','planner_action_bridge_runtime.py'):
        source=(root/name).read_text()
        for token in ('.services.', 'async_call(', 'Store(', 'async_sync_automatic_plans(',
                      'async_handoff_automatic_plans(', 'calculate_plan72(', 'calculate_energy_need('):
            assert token not in source
