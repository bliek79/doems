"""Observable runtime races, exact source windows and HA entity semantics.

The small HA boundary double forbids service/network calls and off-loop state
reads. Real price/solar accessors and the real Energy Need calculation are
used; the concurrency tests gate executor jobs deliberately.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import threading
import types

import pytest

INTEGRATION = Path(__file__).resolve().parents[1] / "custom_components" / "doems"
NOW = datetime(2026, 10, 29, 10, 16, tzinfo=timezone.utc)


@pytest.fixture
def environment(monkeypatch):
    clock = types.SimpleNamespace(now=NOW)
    trackers = []

    def make_module(name, **members):
        module = types.ModuleType(name)
        module.__path__ = []
        module.__dict__.update(members)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    class Entity:
        async def async_added_to_hass(self):
            pass

        async def async_will_remove_from_hass(self):
            pass

        def async_write_ha_state(self):
            pass

    def track(*args, **kwargs):
        registration = {"args": args, "kwargs": kwargs, "active": True}
        trackers.append(registration)

        def unsubscribe():
            registration["active"] = False

        return unsubscribe

    def forbidden(*args, **kwargs):
        raise AssertionError("Plan72 must not contact providers or call device services")

    make_module("homeassistant")
    make_module("homeassistant.components")
    make_module("homeassistant.components.sensor", SensorEntity=Entity, SensorDeviceClass=types.SimpleNamespace(
        ENERGY="energy", BATTERY="battery", DURATION="duration", TIMESTAMP="timestamp"
    ))
    make_module("homeassistant.components.binary_sensor", BinarySensorEntity=Entity)
    make_module("homeassistant.config_entries", ConfigEntry=object)
    make_module("homeassistant.core", HomeAssistant=object, Event=object, callback=lambda fn: fn)
    make_module("homeassistant.helpers")
    make_module("homeassistant.helpers.device_registry", DeviceInfo=dict)
    make_module("homeassistant.helpers.event", async_track_state_change_event=track,
                async_track_time_change=track, async_track_time_interval=track)
    make_module("homeassistant.helpers.aiohttp_client", async_get_clientsession=forbidden)
    dt = make_module("homeassistant.util.dt", utcnow=lambda: clock.now,
                     as_utc=lambda t: t.astimezone(timezone.utc),
                     as_local=lambda t: t, UTC=timezone.utc)
    make_module("homeassistant.util", dt=dt)
    make_module("aiohttp", ClientError=type("ClientError", (Exception,), {}))

    package_name = "doems_plan72_runtime_case"
    package = make_module(package_name)
    package.__path__ = [str(INTEGRATION)]
    make_module(package_name + ".solar_foundation", SolarFoundationManager=object)
    runtime_module = importlib.import_module(package_name + ".planner_72h_runtime")
    prices_module = importlib.import_module(package_name + ".prices")
    solar_module = importlib.import_module(package_name + ".solar_forecast")
    price_model = importlib.import_module(package_name + ".prices_model")

    env = types.SimpleNamespace(runtime=runtime_module, prices=prices_module,
                                solar=solar_module, price_model=price_model,
                                clock=clock, trackers=trackers, forbidden=forbidden)
    yield env
    for name in list(sys.modules):
        if name.startswith(package_name + "."):
            sys.modules.pop(name, None)


class Source:
    def __init__(self):
        self.listeners = []

    def async_add_listener(self, listener):
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener) if listener in self.listeners else None

    def emit(self):
        for listener in tuple(self.listeners):
            listener()


class Coordinator(Source):
    profile = "normal"

    def forecast(self, *, now):
        floor = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
        start = floor if now == floor else floor + timedelta(minutes=15)
        return [types.SimpleNamespace(start=start + timedelta(minutes=i * 15), energy_kwh=0.02)
                for i in range(288)]


class States:
    def __init__(self):
        self.thread = threading.get_ident()
        self.values = {
            "sensor.battery_soc": types.SimpleNamespace(state="60", attributes={"unit_of_measurement": "%"}),
            "sensor.battery_capacity": types.SimpleNamespace(state="7.2", attributes={"unit_of_measurement": "kWh"}),
            "number.battery_minimum": types.SimpleNamespace(state="5", attributes={"unit_of_measurement": "%"}),
        }

    def get(self, entity_id):
        assert threading.get_ident() == self.thread, "HA state read in executor worker"
        return self.values.get(entity_id)


class Hass:
    def __init__(self, forbidden, *, gated=False):
        self.states = States()
        self.services = types.SimpleNamespace(async_call=forbidden)
        self.gated = gated
        self.jobs = []
        self.active_jobs = 0
        self.max_active_jobs = 0

    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)

    async def async_add_executor_job(self, function, inputs):
        gate = asyncio.get_running_loop().create_future()
        job = types.SimpleNamespace(function=function, inputs=inputs, gate=gate)
        self.jobs.append(job)
        self.active_jobs += 1
        self.max_active_jobs = max(self.max_active_jobs, self.active_jobs)
        try:
            if self.gated:
                await gate
            # Home Assistant owns its executor; keep this test worker separate
            # from asyncio.run's implicit default-executor lifecycle as well.
            with ThreadPoolExecutor(max_workers=1) as executor:
                return await asyncio.get_running_loop().run_in_executor(executor, function, inputs)
        finally:
            self.active_jobs -= 1


def setup_runtime(env, *, gated=False):
    hass = Hass(env.forbidden, gated=gated)
    entry = types.SimpleNamespace(options={
        "energy_need_soc_entity": "sensor.battery_soc",
        "energy_need_capacity_entity": "sensor.battery_capacity",
        "energy_need_min_soc_entity": "number.battery_minimum",
        "energy_need_reserve_percent": 5.0,
        "energy_need_roundtrip_efficiency": 84.64,
        "plan72_max_charge_power_w": 3200.0,
        "plan72_max_discharge_power_w": 3200.0,
        "plan72_minimum_trade_margin": 0.10,
        "plan72_trade_enabled": False,
    })
    coordinator = Coordinator()
    foundation = types.SimpleNamespace(snapshot={"enabled": True, "status": "ready"})
    solar = env.solar.SolarForecastManager(hass, foundation)
    solar.last_successful_update = env.clock.now
    old_start = NOW.replace(minute=15)
    solar._source_points = [
        types.SimpleNamespace(start=old_start + timedelta(minutes=15 * i), total_kwh=0.05)
        for i in range(304)
    ]
    prices = env.prices.DOEMSPricesManager(hass, entry)
    prices.status = "ok"
    prices.last_update = env.clock.now
    price_points = [
        env.price_model.PricePoint(old_start + timedelta(minutes=15 * i), 0.1, 0.121,
                                   0.20 + i / 10000, 0.05, "known_pt15m", 15)
        for i in range(304)
    ]
    prices.points = price_points[:288]  # Intentionally begins one quarter too early.
    prices._price_buffer_by_start = {point.start: point for point in price_points}
    need = Source()
    need.snapshot = {"valid": False, "reason": "old_snapshot"}
    runtime = env.runtime.Plan72Runtime(hass, entry, coordinator, solar, prices, need)
    return runtime, hass


async def wait_until(condition):
    async def poll():
        while not condition():
            await asyncio.sleep(0.001)
    await asyncio.wait_for(poll(), timeout=5)


async def finish(runtime):
    await wait_until(lambda: runtime._worker_task is None)


def fake_engine(home, solar, prices, **parameters):
    return {
        "status": "ready", "valid": True, "reason": "complete",
        "slot_count": len(home), "timeline": [{"start": home[0]["start"].isoformat(), "price": prices[0]["import_all_in"]}],
        "start_soc": float(parameters["soc_percent"]),
        "reserve_satisfied": True, "trade": {"profitable": False}, "totals": {},
    }


def test_real_engine_uses_current_price_window_and_consistent_energy_need(environment):
    async def scenario():
        runtime, hass = setup_runtime(environment)
        observed = NOW - timedelta(seconds=30)
        hass.states.values["sensor.battery_soc"].last_updated = observed
        runtime.prices._price_buffer_by_start[NOW.replace(minute=30)].kind = "known_hourly_fallback"
        runtime.prices._price_buffer_by_start[NOW.replace(minute=30)].source_resolution_minutes = 60
        await runtime.async_setup()
        await finish(runtime)
        result = runtime.snapshot
        assert result["valid"] is True
        assert result["slot_count"] == 288
        assert result["action_window_contract"] == "quarter_windows_v1"
        assert result["battery_parameters"]["max_charge_power_w"] == 3200.0
        assert result["timeline"][0]["start"] == "2026-10-29T10:30:00+00:00"
        assert result["timeline"][0]["import_all_in"] == pytest.approx(0.2001)
        assert result["timeline"][-1]["import_all_in"] == pytest.approx(0.2288)
        assert result["timeline"][0]["kind"] == "known_hourly_fallback"
        assert result["timeline"][0]["source_resolution_minutes"] == 60
        assert result["timeline"][1]["source_resolution_minutes"] == 15
        assert result["sources"]["soc_observed_at"] == observed.isoformat()
        assert result["sources"]["horizon_start_assumption"] == "latest_measured_soc_at_next_complete_quarter"
        assert result["sources"]["unmodelled_start_minutes"] == 14.0
        assert result["start_soc"] == 60.0
        assert result["energy_need"]["valid"] is True
        assert runtime.energy_need.snapshot == {"valid": False, "reason": "old_snapshot"}
        assert result["execution_enabled"] is False
        assert result["physical_execution_authority"] is False
        assert hass.max_active_jobs == 1
        await runtime.async_shutdown()
    asyncio.run(scenario())


def test_same_inputs_and_gas_only_notification_do_not_recompute(environment, monkeypatch):
    monkeypatch.setattr(environment.runtime, "calculate_plan72", fake_engine)
    async def scenario():
        runtime, hass = setup_runtime(environment)
        await runtime.async_setup()
        await finish(runtime)
        first_generation = runtime.snapshot["plan_generation"]
        environment.clock.now += timedelta(seconds=20)
        runtime.prices._notify()  # The manager also notifies after gas-only changes.
        runtime.energy_need.emit()
        runtime.refresh("duplicate")
        await asyncio.sleep(0)
        assert len(hass.jobs) == 1
        assert runtime.snapshot["plan_generation"] == first_generation
        assert runtime.snapshot["replan_reason"] == "startup"
        await runtime.async_shutdown()
    asyncio.run(scenario())


def test_pending_changes_coalesce_and_superseded_result_is_never_published(environment, monkeypatch):
    monkeypatch.setattr(environment.runtime, "calculate_plan72", fake_engine)
    async def scenario():
        runtime, hass = setup_runtime(environment, gated=True)
        published = []
        runtime.async_add_listener(lambda: published.append(dict(runtime.snapshot)))
        await runtime.async_setup()
        await wait_until(lambda: len(hass.jobs) == 1)
        hass.states.values["sensor.battery_soc"].state = "50"
        runtime.refresh("battery_changed")
        hass.states.values["sensor.battery_soc"].state = "40"
        runtime.refresh("battery_changed")
        assert runtime.snapshot["valid"] is False
        assert runtime.snapshot["timeline"] == []
        hass.jobs[0].gate.set_result(None)
        await wait_until(lambda: len(hass.jobs) == 2)
        assert not any(item.get("valid") for item in published)
        hass.jobs[1].gate.set_result(None)
        await finish(runtime)
        assert [item["start_soc"] for item in published if item.get("valid")] == [40.0]
        assert len(hass.jobs) == 2
        assert hass.max_active_jobs == 1
        # Job 1 retained its own primitive snapshot when the HA states changed.
        assert dict(hass.jobs[0].inputs.parameters)["soc_percent"] == "60"
        await runtime.async_shutdown()
    asyncio.run(scenario())


def test_lost_source_invalidates_running_generation_and_recovers(environment, monkeypatch):
    monkeypatch.setattr(environment.runtime, "calculate_plan72", fake_engine)
    async def scenario():
        runtime, hass = setup_runtime(environment, gated=True)
        await runtime.async_setup()
        await wait_until(lambda: len(hass.jobs) == 1)
        runtime.solar.last_error = "provider_timeout"
        runtime.solar._notify()
        assert runtime.snapshot["valid"] is False
        assert runtime.snapshot["reason"] == "solar_source_stale"
        hass.jobs[0].gate.set_result(None)
        await finish(runtime)
        assert runtime.snapshot["valid"] is False
        runtime.solar.last_error = None
        runtime.solar._notify()
        await wait_until(lambda: len(hass.jobs) == 2)
        hass.jobs[1].gate.set_result(None)
        await finish(runtime)
        assert runtime.snapshot["valid"] is True
        await runtime.async_shutdown()
    asyncio.run(scenario())


def test_quarter_change_during_worker_rejects_old_window_without_waiting_for_tick(environment, monkeypatch):
    monkeypatch.setattr(environment.runtime, "calculate_plan72", fake_engine)
    async def scenario():
        runtime, hass = setup_runtime(environment, gated=True)
        await runtime.async_setup()
        await wait_until(lambda: len(hass.jobs) == 1)
        environment.clock.now = NOW.replace(minute=31)
        hass.jobs[0].gate.set_result(None)
        await wait_until(lambda: len(hass.jobs) == 2)
        assert runtime.snapshot["valid"] is False
        assert hass.jobs[1].inputs.home[0][0] == NOW.replace(minute=45)
        hass.jobs[1].gate.set_result(None)
        await finish(runtime)
        assert runtime.snapshot["valid"] is True
        assert runtime.snapshot["input_captured_at"] == environment.clock.now.isoformat()
        await runtime.async_shutdown()
    asyncio.run(scenario())


def test_shutdown_removes_subscriptions_and_cannot_publish_or_restart(environment, monkeypatch):
    monkeypatch.setattr(environment.runtime, "calculate_plan72", fake_engine)
    async def scenario():
        runtime, hass = setup_runtime(environment, gated=True)
        await runtime.async_setup()
        await wait_until(lambda: len(hass.jobs) == 1)
        await runtime.async_shutdown()
        before = dict(runtime.snapshot)
        runtime.refresh("late_notification")
        runtime.coordinator.emit()
        runtime.solar._notify()
        runtime.prices._notify()
        assert runtime.snapshot == before
        assert runtime._worker_task is None
        assert len(hass.jobs) == 1
        assert all(not token["active"] for token in environment.trackers)
        assert not runtime.coordinator.listeners
        assert not runtime.solar._listeners
        assert not runtime.prices.listeners
        assert not runtime.energy_need.listeners
    asyncio.run(scenario())


@pytest.mark.parametrize("mutation,reason", [
    (lambda runtime, hass: runtime.entry.options.pop("plan72_max_charge_power_w"), "plan72_power_limits_not_configured"),
    (lambda runtime, hass: setattr(runtime, "prices", None), "missing_dependency_prices"),
    (lambda runtime, hass: setattr(hass.states.values["sensor.battery_soc"], "state", "unavailable"), "battery_source_unavailable_soc_percent"),
    (lambda runtime, hass: setattr(runtime.prices, "last_update", NOW - timedelta(hours=29)), "prices_source_stale"),
    (lambda runtime, hass: runtime.entry.options.update(energy_need_roundtrip_efficiency=float("nan")), "invalid_roundtrip_efficiency"),
    (lambda runtime, hass: setattr(runtime.prices._price_buffer_by_start[NOW.replace(minute=30)], "import_all_in", float("nan")), "nonfinite_planner_input"),
])
def test_missing_legacy_options_and_invalid_sources_fail_closed_without_jobs(environment, mutation, reason):
    async def scenario():
        runtime, hass = setup_runtime(environment)
        mutation(runtime, hass)
        await runtime.async_setup()
        assert runtime.snapshot["status"] == "invalid"
        assert runtime.snapshot["reason"] == reason
        assert runtime.snapshot["valid"] is False
        assert runtime.snapshot["timeline"] == []
        assert not hass.jobs
        await runtime.async_shutdown()
    asyncio.run(scenario())


def test_missing_price_does_not_shift_neighboring_prices(environment):
    async def scenario():
        runtime, hass = setup_runtime(environment)
        missing = NOW.replace(minute=45)
        runtime.prices._price_buffer_by_start.pop(missing)
        await runtime.async_setup()
        assert runtime.snapshot["reason"] == "missing_price_quarters"
        assert runtime.snapshot["valid"] is False
        assert not hass.jobs
        await runtime.async_shutdown()
    asyncio.run(scenario())


def test_worker_failure_is_visible_and_new_input_can_recover(environment, monkeypatch):
    def broken_engine(*args, **kwargs):
        raise ArithmeticError("deliberate_test_failure")
    monkeypatch.setattr(environment.runtime, "calculate_plan72", broken_engine)
    async def scenario():
        runtime, hass = setup_runtime(environment)
        await runtime.async_setup()
        await finish(runtime)
        assert runtime.snapshot["reason"] == "calculation_failed"
        assert runtime.snapshot["valid"] is False
        assert runtime.snapshot["timeline"] == []
        monkeypatch.setattr(environment.runtime, "calculate_plan72", fake_engine)
        hass.states.values["sensor.battery_soc"].state = "61"
        runtime.refresh("battery_changed")
        await finish(runtime)
        assert runtime.snapshot["valid"] is True
        assert runtime.snapshot["start_soc"] == 61.0
        await runtime.async_shutdown()
    asyncio.run(scenario())


def test_accessors_do_not_mutate_public_lists_and_report_duplicates(environment):
    runtime, _ = setup_runtime(environment)
    start = NOW.replace(minute=30)
    public_prices = list(runtime.prices.points)
    source_solar = list(runtime.solar._source_points)
    selected, missing = runtime.prices.forecast_window(start=start)
    assert not missing and len(selected) == 288
    assert selected[0].start == start
    assert runtime.prices.points == public_prices
    solar, missing = runtime.solar.forecast_window(start=start)
    assert not missing and len(solar) == 288
    assert runtime.solar._source_points == source_solar
    runtime.solar._source_points.append(solar[3])
    solar, missing = runtime.solar.forecast_window(start=start)
    assert missing == [start + timedelta(minutes=45)]
    assert len(solar) == 287


def test_entity_ids_units_timestamps_and_invalid_values(environment):
    runtime, _ = setup_runtime(environment)
    sensors = environment.runtime.build_plan72_sensors(runtime)
    binaries = environment.runtime.build_plan72_binary_sensors(runtime)
    identifiers = [entity._attr_unique_id for entity in [*sensors, *binaries]]
    assert len(identifiers) == len(set(identifiers)) == 35
    assert "action_windows" in sensors[0]._unrecorded_attributes
    assert all(value.startswith("doems_ems_plan72_") for value in identifiers)
    indexed = {sensor.field.key: sensor for sensor in sensors}
    runtime.snapshot = {"valid": True, "execution_reserve_kwh": 0.72,
                        "trade": {"best_charge_time": "2026-10-29T12:00:00+00:00", "profitable": True}}
    assert indexed["reserve"].native_value == 0.72
    assert indexed["reserve"]._attr_native_unit_of_measurement == "kWh"
    assert indexed["best_charge_time"].native_value == NOW.replace(hour=12, minute=0)
    assert indexed["best_charge_time"]._attr_device_class == "timestamp"
    assert binaries[0].is_on is True and binaries[2].is_on is True
    assert all(entity.extra_state_attributes["physical_execution_authority"] is False for entity in [*sensors, *binaries])
    runtime.snapshot["valid"] = False
    assert indexed["reserve"].native_value is None
    assert indexed["best_charge_time"].native_value is None
    assert binaries[0].is_on is False and binaries[2].is_on is None


def test_store_change_during_worker_discards_old_manual_generation(environment, monkeypatch):
    class Plans:
        def __init__(self):
            self.listeners = []
            self.plans = {1: dict(origin='manual', execution_mode='gepland', action='laden',
                lifecycle_status='concept', start_time='2026-10-29T11:00:00+00:00',
                power_w=1000, target_soc=80, max_runtime_h=.25)}
        def get_plan(self, slot): return dict(self.plans.get(slot, {}))
        def add_listener(self, listener):
            self.listeners.append(listener)
            return lambda: self.listeners.remove(listener)
        def emit(self):
            for listener in tuple(self.listeners): listener()
    received = []
    def engine(home, solar, prices, **parameters):
        received.append(parameters['manual_plans'])
        return fake_engine(home, solar, prices, **parameters)
    monkeypatch.setattr(environment.runtime, 'calculate_plan72', engine)
    async def scenario():
        runtime, hass = setup_runtime(environment, gated=True)
        store = Plans()
        runtime.plan_store = store
        await runtime.async_setup()
        await wait_until(lambda: len(hass.jobs) == 1)
        old_fingerprint = hass.jobs[0].inputs.fingerprint
        store.plans[1]['power_w'] = 2000
        store.emit()
        hass.jobs[0].gate.set_result(None)
        await wait_until(lambda: len(hass.jobs) == 2)
        assert runtime.snapshot['status'] == 'calculating'
        hass.jobs[1].gate.set_result(None)
        await finish(runtime)
        assert received[0][0]['power_w'] == 1000
        assert received[1][0]['power_w'] == 2000
        assert runtime.snapshot['input_fingerprint'] != old_fingerprint
        assert runtime.snapshot['sources']['manual_input'] == 'plan_store'
        assert runtime.snapshot['physical_execution_authority'] is False
        await runtime.async_shutdown()
        assert not store.listeners
    asyncio.run(scenario())
