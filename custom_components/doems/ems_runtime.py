"""DOEMS EMS planning/runtime orchestration.

The native planner remains 15 minutes / 72 hours / 288 slots. The runtime keeps
the frozen Alpha76 EMS decision/execution semantics while adapting transport and
scheduling to native DOEMS data. Alpha33 serializes coordinator-state publication
so the copied Alpha76 execution controller always observes one consistent
Scheduler/Safety snapshot during mode transitions. Alpha34 adds a narrow host
verification of physical setpoint acceptance without changing Alpha76 execution
or monitor semantics.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_CHARGE_POWER_ENTITY,
    CONF_BATTERY_DISCHARGE_POWER_ENTITY,
    CONF_DEVICE_STATUS_ENTITY,
    CONF_SOC_ENTITY,
    CONTROL_PATH_OBSERVER_INTERVAL_SECONDS,
    DOMAIN,
)
from .ems_multirate import (
    MULTIRATE_RUNTIME_VERSION,
    is_planner_trigger,
    planner_cycle_id,
    planner_input_signature,
    run_planner_worker,
)
from .ems_action_controller import DOEMSActionController
from .ems_automatic_execution_gate import DOEMSAutomaticExecutionGate
from .ems_control_path import DOEMSControlPathObserver
from .ems_execution import DOEMSExecutionController
from .ems_physical_test import DOEMSPhysicalTestController
from .ems_plan_store import DOEMSPlanStore
from .ems_prestart_validator import DOEMSPreStartValidator
from .ems_safety_guard import DOEMSSafetyGuard
from .ems_scheduler import DOEMSScheduler
from .ems_planner_bridge import build_planner_action_bridge
from .ems_live_input import build_live_ems_input
from .ems_settings import EMSSettings
from .ems_soc import UNAVAILABLE_SOC_STATES, parse_soc_percent
from .energy_sources import normalize_power_w

_LOGGER = logging.getLogger(__name__)

# Alpha34 host-adapter constants. The tolerance deliberately matches the frozen
# Alpha76 execution monitor and therefore does not relax source safety semantics.
_PLATFORM_SETPOINT_HANDOFF_TOLERANCE_W = 10.0
_PLATFORM_SETPOINT_HANDOFF_SETTLE_SECONDS = 0.25
_PLATFORM_SETPOINT_HANDOFF_SAMPLE_SECONDS = 0.20
_PLATFORM_SETPOINT_HANDOFF_SAMPLE_COUNT = 3


class DOEMSEMSRuntime:
    """Independent DOEMS planning runtime; non-actuating in Alpha8."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        settings: EMSSettings,
        coordinator: Any,
        solar_forecast: Any,
        prices: Any,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.settings = settings
        self.coordinator = coordinator
        self.solar_forecast = solar_forecast
        self.prices = prices

        self.status = "not_started"
        self.last_refresh: datetime | None = None
        self.last_trigger = "not_started"
        self.refresh_count = 0
        self.last_error: str | None = None
        self.input_result: dict[str, Any] | None = None
        self.planner_result: dict[str, Any] | None = None
        self.soc_percent: float | None = None
        self.soc_source_status = "not_configured"
        self.soc_last_updated: str | None = None
        self.plan_store = DOEMSPlanStore(hass, entry.entry_id)
        self.scheduler = DOEMSScheduler(self.plan_store)
        self.prestart_validator = DOEMSPreStartValidator()
        self.safety_guard = DOEMSSafetyGuard()
        self.action_controller = DOEMSActionController()
        self.automatic_execution_gate = DOEMSAutomaticExecutionGate()
        self.execution = DOEMSExecutionController(hass, entry.entry_id)
        self.physical_test = DOEMSPhysicalTestController(hass, entry.entry_id)
        self.control_path = DOEMSControlPathObserver(hass, entry)
        self.bridge_result: dict[str, Any] = {}
        self.scheduler_result: dict[str, Any] = {}
        self.plan_store_result: dict[str, Any] = {}
        self.handoff_result: dict[str, Any] = {}
        self.expired_release_result: dict[str, Any] = {}
        self.prestart_result: dict[str, Any] = {}
        self.safety_result: dict[str, Any] = {}
        self.execution_handoff_result: dict[str, Any] = {}
        self.final_revalidation_result: dict[str, Any] = {}
        self.mode_switch_preview_result: dict[str, Any] = {}
        self.automatic_execution_gate_result: dict[str, Any] = {}
        self.execution_result: dict[str, Any] = {}
        self.legacy_safety_result: dict[str, Any] = {}
        self.action_controller_result: dict[str, Any] = {}
        self.control_path_result: dict[str, Any] = self.control_path.evaluate()
        self._source_data_result: dict[str, Any] = {}
        # Compatibility diagnostics: the real Alpha76 controller owns its own
        # Store exactly as in the source integration.
        self.execution_store_status = "alpha76_native_store"
        self.execution_store_error: str | None = None
        self.execution_store_last_saved_at: str | None = None
        # Canonical Alpha34 platform adapter diagnostics. These fields confirm
        # whether the Home Assistant control entity retained the setpoint after
        # the frozen Alpha76 controller handed it to the host integration.
        self._setpoint_handoff_status = "idle"
        self._setpoint_handoff_expected_w: float | None = None
        self._setpoint_handoff_observed_w: float | None = None
        self._setpoint_handoff_samples: list[float | None] = []
        self._setpoint_handoff_last_checked_at: str | None = None
        self._setpoint_handoff_failure_count = 0

        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._fast_refresh_pending = False
        # Behavior-preserving platform adapter: Anker alpha76 gets one serialized
        # DataUpdateCoordinator snapshot. DOEMS keeps its native multi-rate runtime,
        # but all planner publication and fast execution-state refreshes cross this
        # single lock before publishing shared Scheduler/Safety/Execution state.
        self._state_publish_lock = asyncio.Lock()
        self._shutdown = False
        self._planner_task: asyncio.Task[None] | None = None
        self._planner_pending_triggers: set[str] = set()
        self._planner_generation = 0
        self._planner_published_generation = 0
        self._planner_compute_count = 0
        self._planner_stale_discard_count = 0
        self._planner_same_signature_skip_count = 0
        self._planner_last_input_signature: str | None = None
        self._planner_last_cycle_id: str | None = None
        self._planner_last_refresh: datetime | None = None
        self._planner_debounce_seconds = 2.0
        self._planner_publish_active = False
        self._deferred_fast_trigger: str | None = None
        self._scheduled_manual_start_task: asyncio.Task[None] | None = None
        self._automatic_execution_task: asyncio.Task[None] | None = None
        # Runtime starts false; the Home Assistant RestoreEntity switch restores
        # the saved Alpha76 live_guarded state after platform setup.
        self._automatic_execution_armed = False
        self._control_path_timer_unsub: Callable[[], None] | None = None
        self._execution_timer_unsub: Callable[[], None] | None = None
        self._planner_quarter_timer_unsub: Callable[[], None] | None = None

    @property
    def automatic_execution_armed(self) -> bool:
        return self._automatic_execution_armed

    async def async_set_automatic_execution_armed(self, armed: bool) -> None:
        """Set the frozen Alpha76 arm for automatic planner execution only."""
        self._automatic_execution_armed = bool(armed)
        await self._async_fast_execution_refresh("automatic_execution_arm_change")

    @property
    def soc_entity_id(self) -> str | None:
        value = self.entry.options.get(CONF_SOC_ENTITY)
        return str(value) if value else None

    async def async_setup(self) -> None:
        """Load DOEMS plans, execution audit state, listeners and first refresh."""
        await self.plan_store.async_load()
        await self.physical_test.async_load()
        await self.execution.async_load()
        self.physical_test.attach_coordinator(self)
        self.execution.attach_coordinator(self)
        self._unsubs.append(
            self.plan_store.add_listener(
                lambda: self._request_fast_refresh("plan_store_change")
            )
        )
        for source, trigger in (
            (self.coordinator, "energy_forecast_update"),
            (self.solar_forecast, "solar_forecast_update"),
            (self.prices, "prices_forecast_update"),
        ):
            if source is not None and hasattr(source, "async_add_listener"):
                self._unsubs.append(
                    source.async_add_listener(
                        lambda trigger=trigger: self._request_planner_refresh(trigger)
                    )
                )

        if self.soc_entity_id:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    [self.soc_entity_id],
                    self._soc_state_changed,
                )
            )

        control_entities = [
            entity_id
            for entity_id in self.control_path.entity_ids.values()
            if entity_id
        ]
        if control_entities:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    control_entities,
                    self._control_path_state_changed,
                )
            )
            self._schedule_control_path_tick()

        await self.async_refresh("startup")
        # Source-parity restart recovery: an interrupted physical transaction is
        # safe-stopped; the Automatic Execution arm itself is restored separately
        # by the switch RestoreEntity path.
        await self.physical_test.async_recover_if_needed()
        await self.execution.async_recover_if_needed()
        self._schedule_planner_quarter_tick()
        self._schedule_execution_tick()

    async def async_shutdown(self) -> None:
        """Safe-stop Alpha76 physical controllers and stop DOEMS runtime tasks."""
        if (
            self._scheduled_manual_start_task is not None
            and not self._scheduled_manual_start_task.done()
        ):
            self._scheduled_manual_start_task.cancel()
            self._scheduled_manual_start_task = None
        if (
            self._automatic_execution_task is not None
            and not self._automatic_execution_task.done()
        ):
            self._automatic_execution_task.cancel()
            self._automatic_execution_task = None

        await self.physical_test.async_shutdown_stop()
        await self.execution.async_shutdown_stop()
        self._shutdown = True
        if self._control_path_timer_unsub is not None:
            self._control_path_timer_unsub()
            self._control_path_timer_unsub = None
        if self._execution_timer_unsub is not None:
            self._execution_timer_unsub()
            self._execution_timer_unsub = None
        if self._planner_quarter_timer_unsub is not None:
            self._planner_quarter_timer_unsub()
            self._planner_quarter_timer_unsub = None
        if self._planner_task is not None:
            self._planner_task.cancel()
            self._planner_task = None
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._listeners.clear()

    async def _async_load_execution(self) -> None:
        """Compatibility no-op: Alpha76 execution owns its native Store."""
        self.execution_store_status = "alpha76_native_store"
        self.execution_store_error = None

    async def _async_persist_execution_if_changed(self) -> None:
        """Compatibility no-op retained for old diagnostics only."""
        return

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def remove_listener() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove_listener

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def _soc_state_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data.get("new_state")
        recovered = False
        if self.soc_percent is None and new_state is not None:
            state_value = getattr(new_state, "state", None)
            if state_value not in UNAVAILABLE_SOC_STATES:
                recovered = parse_soc_percent(state_value) is not None
        self._request_fast_refresh("soc_state_change")
        if recovered:
            self._request_planner_refresh("soc_recovered")

    @callback
    def _control_path_state_changed(self, _event: Event[EventStateChangedData]) -> None:
        self.control_path_result = self.control_path.evaluate()
        self._request_fast_refresh("control_path_state_change")

    @callback
    def _schedule_control_path_tick(self) -> None:
        if self._shutdown or self._control_path_timer_unsub is not None:
            return
        self._control_path_timer_unsub = async_call_later(
            self.hass,
            CONTROL_PATH_OBSERVER_INTERVAL_SECONDS,
            self._control_path_tick,
        )

    @callback
    def _control_path_tick(self, _now: datetime) -> None:
        self._control_path_timer_unsub = None
        if self._shutdown:
            return
        self.control_path_result = self.control_path.evaluate()
        self._notify()
        self._schedule_control_path_tick()

    @callback
    def _schedule_execution_tick(self) -> None:
        if self._shutdown or self._execution_timer_unsub is not None:
            return
        self._execution_timer_unsub = async_call_later(
            self.hass,
            5,
            self._execution_tick,
        )

    @callback
    def _execution_tick(self, _now: datetime) -> None:
        self._execution_timer_unsub = None
        if self._shutdown:
            return
        self._request_fast_refresh("execution_monitor")
        self._schedule_execution_tick()

    @callback
    def _schedule_planner_quarter_tick(self) -> None:
        if self._shutdown or self._planner_quarter_timer_unsub is not None:
            return
        now = dt_util.utcnow()
        minute = (now.minute // 15 + 1) * 15
        if minute >= 60:
            next_quarter = (now + timedelta(hours=1)).replace(
                minute=0,
                second=3,
                microsecond=0,
            )
        else:
            next_quarter = now.replace(
                minute=minute,
                second=3,
                microsecond=0,
            )
        delay = max(0.1, (next_quarter - now).total_seconds())
        self._planner_quarter_timer_unsub = async_call_later(
            self.hass,
            delay,
            self._planner_quarter_tick,
        )

    @callback
    def _planner_quarter_tick(self, _now: datetime) -> None:
        self._planner_quarter_timer_unsub = None
        if self._shutdown:
            return
        self._request_planner_refresh("quarter_boundary")
        self._schedule_planner_quarter_tick()

    @callback
    def _request_fast_refresh(self, trigger: str) -> None:
        if self._shutdown:
            return
        if self._planner_publish_active:
            self._deferred_fast_trigger = trigger
            return
        if self._fast_refresh_pending:
            return
        self._fast_refresh_pending = True
        self.hass.async_create_task(self._async_requested_fast_refresh(trigger))

    async def _async_requested_fast_refresh(self, trigger: str) -> None:
        try:
            await asyncio.sleep(0)
            if not self._shutdown:
                await self._async_fast_execution_refresh(trigger)
        finally:
            self._fast_refresh_pending = False

    @callback
    def _request_planner_refresh(self, trigger: str) -> None:
        if self._shutdown:
            return
        self._planner_generation += 1
        self._planner_pending_triggers.add(trigger)
        if self._planner_task is None or self._planner_task.done():
            self._planner_task = self.hass.async_create_task(
                self._async_planner_loop()
            )

    @callback
    def _request_refresh(self, trigger: str) -> None:
        """Compatibility dispatcher for existing internal callers."""
        if is_planner_trigger(trigger):
            self._request_planner_refresh(trigger)
        else:
            self._request_fast_refresh(trigger)

    async def _async_planner_loop(self) -> None:
        try:
            first_iteration = True
            while self._planner_pending_triggers and not self._shutdown:
                immediate = first_iteration and "startup" in self._planner_pending_triggers
                if not immediate:
                    await asyncio.sleep(self._planner_debounce_seconds)
                generation = self._planner_generation
                triggers = sorted(self._planner_pending_triggers)
                self._planner_pending_triggers.clear()
                await self._async_run_planner_generation(generation, triggers)
                first_iteration = False
        finally:
            self._planner_task = None
            if self._planner_pending_triggers and not self._shutdown:
                self._planner_task = self.hass.async_create_task(
                    self._async_planner_loop()
                )

    def _read_soc(self) -> tuple[float | None, str, str | None]:
        entity_id = self.soc_entity_id
        if not entity_id:
            return None, "not_configured", None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None, "entity_missing", None
        updated = state.last_updated.isoformat()
        if state.state in UNAVAILABLE_SOC_STATES:
            return None, "unavailable", updated
        value = parse_soc_percent(state.state)
        if value is None:
            return None, "invalid_value", updated
        return value, "ok", updated

    def _read_optional_state(self, option_key: str) -> str | None:
        """Read one configured diagnostic source as a raw state string."""
        entity_id = self.entry.options.get(option_key)
        if not entity_id:
            return None
        state = self.hass.states.get(str(entity_id))
        if state is None or state.state in UNAVAILABLE_SOC_STATES:
            return None
        return str(state.state)

    def _read_optional_power(self, option_key: str) -> float | None:
        """Read one already-configured battery power source without adding control."""
        entity_id = self.entry.options.get(option_key)
        if not entity_id:
            return None
        state = self.hass.states.get(str(entity_id))
        if state is None:
            return None
        return normalize_power_w(
            state.state,
            state.attributes.get("unit_of_measurement"),
            allow_negative=False,
        )

    async def async_refresh(self, trigger: str = "execution_refresh") -> None:
        """Refresh planner only for planner triggers; otherwise run the fast path."""
        if is_planner_trigger(trigger):
            self._planner_generation += 1
            self._planner_pending_triggers.add(trigger)
            if self._planner_task is None or self._planner_task.done():
                self._planner_task = self.hass.async_create_task(
                    self._async_planner_loop()
                )
            task = self._planner_task
            if task is not None:
                await task
            return
        await self._async_fast_execution_refresh(trigger)

    async def _async_run_planner_generation(
        self,
        generation: int,
        triggers: list[str],
    ) -> None:
        """Build one planner generation off-loop and publish only if still current."""
        trigger = "+".join(triggers) if triggers else "planner_refresh"
        reference = dt_util.utcnow()
        self.last_trigger = trigger
        self.last_refresh = reference
        self._planner_last_refresh = reference
        self.refresh_count += 1
        self.last_error = None
        self.control_path_result = self.control_path.evaluate()

        soc, soc_status, soc_updated = self._read_soc()
        self.soc_percent = soc
        self.soc_source_status = soc_status
        self.soc_last_updated = soc_updated

        if not self.soc_entity_id:
            self.status = "waiting_for_soc_source"
            self._notify()
            return
        if soc is None:
            self.status = "waiting_for_valid_soc"
            self._notify()
            return
        if self.coordinator is None or self.solar_forecast is None or self.prices is None:
            self.status = "waiting_for_forecast_components"
            self._notify()
            return

        try:
            input_result = build_live_ems_input(
                coordinator=self.coordinator,
                solar_forecast=self.solar_forecast,
                prices=self.prices,
                reference=reference,
            )
            if (
                input_result.get("status") != "ready"
                or input_result.get("native_valid_slot_count") != 288
                or len(input_result.get("rows") or []) != 72
            ):
                self.input_result = input_result
                self.status = "waiting_for_complete_forecast"
                self._notify()
                return

            signature = planner_input_signature(
                input_result=input_result,
                settings=self.settings,
                soc_percent=soc,
                reference=reference,
            )
            cycle_id = planner_cycle_id(reference)
            if (
                signature == self._planner_last_input_signature
                and self.planner_result is not None
            ):
                self.input_result = input_result
                self._planner_same_signature_skip_count += 1
                self._planner_last_cycle_id = cycle_id
                self.status = "ready"
                await self._async_fast_execution_refresh(
                    "planner_same_signature_fast_path"
                )
                return

            worker = partial(
                run_planner_worker,
                input_result=input_result,
                settings=self.settings,
                soc_percent=soc,
                reference=reference,
            )
            planner_result = await self.hass.async_add_executor_job(worker)
            self._planner_compute_count += 1

            if generation != self._planner_generation:
                self._planner_stale_discard_count += 1
                return

            # Alpha33 platform adapter: heavy planner compute remains off-loop,
            # but publishing its Plan Store/Scheduler snapshot is serialized with
            # every fast execution/control-path refresh. This mirrors the source
            # DataUpdateCoordinator transaction boundary without changing planner
            # or execution semantics.
            async with self._state_publish_lock:
                if generation != self._planner_generation:
                    self._planner_stale_discard_count += 1
                    return
                self.input_result = input_result
                self.planner_result = planner_result
                self._planner_last_input_signature = signature
                self._planner_last_cycle_id = cycle_id
                self._planner_published_generation = generation
                self._planner_publish_active = True
                try:
                    await self._async_run_bridge_planstore_scheduler()
                finally:
                    self._planner_publish_active = False
                    deferred_trigger = self._deferred_fast_trigger
                    self._deferred_fast_trigger = None
                    if deferred_trigger:
                        self._request_fast_refresh(deferred_trigger)
                self.status = "ready"
        except Exception as err:
            self.status = "error"
            self.last_error = f"{type(err).__name__}: {err}"

        self._notify()

    async def _async_run_bridge_planstore_scheduler(self) -> None:
        """Run the copied Bridge -> DOEMS Plan Store -> DOEMS Scheduler chain."""
        planner = self.planner_result or {}
        plan72 = dict(planner.get("plan72") or {})
        data: dict[str, Any] = {
            **plan72,
            "forecast_ready": True,
            "max_charge_power_w": self.settings.max_charge_power_w,
            "max_discharge_power_w": self.settings.max_discharge_power_w,
            "battery_capacity_kwh": self.settings.battery_capacity_kwh,
            "technical_min_soc_percent": self.settings.technical_min_soc_percent,
            "max_soc_percent": self.settings.max_soc_percent,
            "charge_efficiency_percent": self.settings.charge_efficiency_percent,
            "discharge_efficiency_percent": self.settings.discharge_efficiency_percent,
        }

        pre_cleanup_scheduler = self.scheduler.evaluate(
            self.settings.max_charge_power_w,
            self.settings.max_discharge_power_w,
            now=self.last_refresh,
        )
        expired_slots = {
            int(slot)
            for slot, detail in (pre_cleanup_scheduler.get("scheduler_slots") or {}).items()
            if str((detail or {}).get("status") or "").lower() == "verlopen"
        }
        self.expired_release_result = (
            await self.plan_store.async_release_expired_automatic_plans(expired_slots)
        )

        scheduler_snapshot = self.scheduler.evaluate(
            self.settings.max_charge_power_w,
            self.settings.max_discharge_power_w,
            now=self.last_refresh,
        )
        data.update(scheduler_snapshot)

        bridge = build_planner_action_bridge(data, now=self.last_refresh)
        data.update(bridge)

        desired_auto_plans: dict[int, dict[str, Any]] = {}
        write_gate_open = (
            bool(data.get("auto_bridge_valid"))
            and bool(data.get("forecast_ready"))
            and not int(data.get("auto_bridge_invalid_candidate_count") or 0)
        )
        if write_gate_open:
            for proposal in data.get("auto_bridge_slot_preview") or []:
                if not proposal.get("plan_store_write_permitted"):
                    continue
                slot = proposal.get("suggested_slot")
                if isinstance(slot, int):
                    desired_auto_plans[slot] = proposal

        if write_gate_open:
            self.plan_store_result = await self.plan_store.async_sync_automatic_plans(
                desired_auto_plans
            )
        else:
            self.plan_store_result = {
                "changed": False,
                "changed_slots": [],
                "written_slots": [],
                "cleared_slots": [],
                "skipped_slots": [],
                "preserved_due_gate_closed": True,
            }

        handoff_allowed: dict[int, str] = {}
        if write_gate_open:
            for proposal in data.get("auto_bridge_slot_preview") or []:
                if not proposal.get("scheduler_handoff_permitted"):
                    continue
                slot = proposal.get("suggested_slot")
                signature = proposal.get("planner_signature")
                if isinstance(slot, int) and isinstance(signature, str) and signature:
                    handoff_allowed[slot] = signature

        self.handoff_result = await self.plan_store.async_handoff_automatic_plans(
            handoff_allowed if write_gate_open else {}
        )

        self.scheduler_result = self.scheduler.evaluate(
            self.settings.max_charge_power_w,
            self.settings.max_discharge_power_w,
            now=self.last_refresh,
        )
        refreshed_data = {**data, **self.scheduler_result}
        refreshed_bridge = build_planner_action_bridge(
            refreshed_data,
            now=self.last_refresh,
        )
        self.bridge_result = {
            **refreshed_bridge,
            "auto_bridge_plan_store_write_enabled": True,
            "auto_bridge_plan_store_write_gate_open": write_gate_open,
            "auto_bridge_plan_store_preserved_due_gate_closed": self.plan_store_result.get(
                "preserved_due_gate_closed", False
            ),
            "auto_bridge_plan_store_write_changed": self.plan_store_result.get(
                "changed", False
            ),
            "auto_bridge_plan_store_written_slots": self.plan_store_result.get(
                "written_slots", []
            ),
            "auto_bridge_plan_store_cleared_slots": self.plan_store_result.get(
                "cleared_slots", []
            ),
            "auto_bridge_plan_store_skipped_slots": self.plan_store_result.get(
                "skipped_slots", []
            ),
            "auto_bridge_scheduler_handoff_enabled": True,
            "auto_bridge_scheduler_handoff_gate_open": write_gate_open,
            "auto_bridge_scheduler_handoff_changed": self.handoff_result.get(
                "changed", False
            ),
            "auto_bridge_scheduler_handoff_slots": self.handoff_result.get(
                "handed_off_slots", []
            ),
            "auto_bridge_scheduler_handoff_skipped_slots": self.handoff_result.get(
                "skipped_slots", []
            ),
            "auto_bridge_execution_enabled": False,
            "auto_bridge_observational_only": False,
        }

        # Step 11 consumes the Step 12.1 control-path contract read-only.
        # A configured path may remove the former configuration blocker, but
        # no controller, arm gate, service call or physical authority exists.
        control_path = self.control_path_result or self.control_path.evaluate()
        control_entities = control_path.get("entities") or {}
        step11_data: dict[str, Any] = {
            **plan72,
            **self.bridge_result,
            **self.scheduler_result,
            "forecast_ready": True,
            "soc": self.soc_percent,
            "device_status": self._read_optional_state(CONF_DEVICE_STATUS_ENTITY),
            "max_charge_power_w": self.settings.max_charge_power_w,
            "max_discharge_power_w": self.settings.max_discharge_power_w,
            "technical_min_soc_percent": self.settings.technical_min_soc_percent,
            "max_soc_percent": self.settings.max_soc_percent,
            "charge_power_w": self._read_optional_power(
                CONF_BATTERY_CHARGE_POWER_ENTITY
            ),
            "discharge_power_w": self._read_optional_power(
                CONF_BATTERY_DISCHARGE_POWER_ENTITY
            ),
            "control_path_configured": bool(control_path.get("configured")),
            "control_path_ready": control_path.get("ready"),
            "control_path_pre_mode_ready": control_path.get("pre_mode_ready"),
            "control_path_post_mode_ready": control_path.get("post_mode_ready"),
            "control_path_required_stable_seconds": control_path.get("required_stable_seconds", 60),
            "control_path_pre_mode_stable_seconds": control_path.get("pre_mode_stable_seconds", 0),
            "control_path_post_mode_stable_seconds": control_path.get("post_mode_stable_seconds", 0),
            "control_path_entities": control_entities,
            "control_path_operating_mode_available": control_entities.get("operating_mode", {}).get("available", False),
            "operating_mode": control_entities.get("operating_mode", {}).get("state"),
            "action_direction": control_entities.get("action_direction", {}).get("state"),
            "power_setpoint_w": control_entities.get("power_setpoint", {}).get("state"),
            "physical_test_active": bool(self.physical_test.data.get("active")),
            "execution_active": bool(self.execution.data.get("active")),
            "execution_origin": self.execution.data.get("origin"),
        }
        self.prestart_result = self.prestart_validator.evaluate(step11_data)
        step11_data.update(self.prestart_result)
        self.safety_result = self.safety_guard.evaluate_automatic_handoff(step11_data)

        # Frozen Alpha76 downstream path. Handoff, final revalidation and
        # mode-switch preview are evaluated by the same Execution Controller
        # that owns the physical transaction.
        execution_data: dict[str, Any] = {
            **step11_data,
            **self.safety_result,
        }
        self.execution_handoff_result = self.execution.evaluate_automatic_handoff(
            execution_data
        )

        final_data: dict[str, Any] = {
            **execution_data,
            **self.execution_handoff_result,
        }
        self.final_revalidation_result = self.execution.evaluate_final_revalidation(
            final_data
        )
        preview_data: dict[str, Any] = {
            **final_data,
            **self.final_revalidation_result,
        }
        self.mode_switch_preview_result = self.execution.evaluate_mode_switch_transaction(
            preview_data
        )

        gate_data: dict[str, Any] = {
            **preview_data,
            **self.mode_switch_preview_result,
            "physical_test_active": bool(self.physical_test.data.get("active")),
            "execution_active": bool(self.execution.data.get("active")),
            "execution_origin": self.execution.data.get("origin"),
        }
        readiness = self.execution.control_path_readiness()
        self.automatic_execution_gate_result = self.automatic_execution_gate.evaluate(
            gate_data,
            armed=self._automatic_execution_armed,
            readiness=readiness,
        )
        live_execution = self.execution.data
        self.execution_result = {
            **{f"execution_{key}": value for key, value in live_execution.items()},
            "execution_remaining_s": self.execution.remaining_seconds,
        }

        # Step 12.2 manual/legacy observer path. This mirrors the source's
        # separate legacy Safety -> Action Controller evaluation and remains
        # semantic/read-only. It is not part of automatic Plan72 execution.
        self.legacy_safety_result = self.safety_guard.evaluate(step11_data)
        action_data: dict[str, Any] = {
            **step11_data,
            **self.legacy_safety_result,
        }
        self.action_controller_result = self.action_controller.evaluate(action_data)
        self._publish_source_data(plan72=plan72, step11_data=step11_data)
        self._schedule_manual_physical_start()

    async def _async_fast_execution_refresh(self, trigger: str) -> None:
        """Serialize one fast Alpha76-equivalent coordinator snapshot refresh."""
        async with self._state_publish_lock:
            await self._async_fast_execution_refresh_locked(trigger)

    async def _async_fast_execution_refresh_locked(self, trigger: str) -> None:
        """Run Scheduler/Safety/Execution against cached data under the state lock."""
        if self._shutdown:
            return
        self.last_trigger = trigger
        self.last_refresh = dt_util.utcnow()
        self.refresh_count += 1
        self.last_error = None
        self.control_path_result = self.control_path.evaluate()

        soc, soc_status, soc_updated = self._read_soc()
        self.soc_percent = soc
        self.soc_source_status = soc_status
        self.soc_last_updated = soc_updated

        self.scheduler_result = self.scheduler.evaluate(
            self.settings.max_charge_power_w,
            self.settings.max_discharge_power_w,
            now=self.last_refresh,
        )
        planner = self.planner_result or {}
        plan72 = dict(planner.get("plan72") or {})

        # Step 11 consumes the Step 12.1 control-path contract read-only.
        # A configured path may remove the former configuration blocker, but
        # no controller, arm gate, service call or physical authority exists.
        control_path = self.control_path_result or self.control_path.evaluate()
        control_entities = control_path.get("entities") or {}
        step11_data: dict[str, Any] = {
            **plan72,
            **self.bridge_result,
            **self.scheduler_result,
            "forecast_ready": (self.input_result or {}).get("status") == "ready",
            "soc": self.soc_percent,
            "device_status": self._read_optional_state(CONF_DEVICE_STATUS_ENTITY),
            "max_charge_power_w": self.settings.max_charge_power_w,
            "max_discharge_power_w": self.settings.max_discharge_power_w,
            "technical_min_soc_percent": self.settings.technical_min_soc_percent,
            "max_soc_percent": self.settings.max_soc_percent,
            "charge_power_w": self._read_optional_power(
                CONF_BATTERY_CHARGE_POWER_ENTITY
            ),
            "discharge_power_w": self._read_optional_power(
                CONF_BATTERY_DISCHARGE_POWER_ENTITY
            ),
            "control_path_configured": bool(control_path.get("configured")),
            "control_path_ready": control_path.get("ready"),
            "control_path_pre_mode_ready": control_path.get("pre_mode_ready"),
            "control_path_post_mode_ready": control_path.get("post_mode_ready"),
            "control_path_required_stable_seconds": control_path.get("required_stable_seconds", 60),
            "control_path_pre_mode_stable_seconds": control_path.get("pre_mode_stable_seconds", 0),
            "control_path_post_mode_stable_seconds": control_path.get("post_mode_stable_seconds", 0),
            "control_path_entities": control_entities,
            "control_path_operating_mode_available": control_entities.get("operating_mode", {}).get("available", False),
            "operating_mode": control_entities.get("operating_mode", {}).get("state"),
            "action_direction": control_entities.get("action_direction", {}).get("state"),
            "power_setpoint_w": control_entities.get("power_setpoint", {}).get("state"),
            "physical_test_active": bool(self.physical_test.data.get("active")),
            "execution_active": bool(self.execution.data.get("active")),
            "execution_origin": self.execution.data.get("origin"),
        }
        self.prestart_result = self.prestart_validator.evaluate(step11_data)
        step11_data.update(self.prestart_result)
        self.safety_result = self.safety_guard.evaluate_automatic_handoff(step11_data)

        # Frozen Alpha76 downstream path. Handoff, final revalidation and
        # mode-switch preview are evaluated by the same Execution Controller
        # that owns the physical transaction.
        execution_data: dict[str, Any] = {
            **step11_data,
            **self.safety_result,
        }
        self.execution_handoff_result = self.execution.evaluate_automatic_handoff(
            execution_data
        )

        final_data: dict[str, Any] = {
            **execution_data,
            **self.execution_handoff_result,
        }
        self.final_revalidation_result = self.execution.evaluate_final_revalidation(
            final_data
        )
        preview_data: dict[str, Any] = {
            **final_data,
            **self.final_revalidation_result,
        }
        self.mode_switch_preview_result = self.execution.evaluate_mode_switch_transaction(
            preview_data
        )

        gate_data: dict[str, Any] = {
            **preview_data,
            **self.mode_switch_preview_result,
            "physical_test_active": bool(self.physical_test.data.get("active")),
            "execution_active": bool(self.execution.data.get("active")),
            "execution_origin": self.execution.data.get("origin"),
        }
        readiness = self.execution.control_path_readiness()
        self.automatic_execution_gate_result = self.automatic_execution_gate.evaluate(
            gate_data,
            armed=self._automatic_execution_armed,
            readiness=readiness,
        )
        live_execution = self.execution.data
        self.execution_result = {
            **{f"execution_{key}": value for key, value in live_execution.items()},
            "execution_remaining_s": self.execution.remaining_seconds,
        }

        # Step 12.2 manual/legacy observer path. This mirrors the source's
        # separate legacy Safety -> Action Controller evaluation and remains
        # semantic/read-only. It is not part of automatic Plan72 execution.
        self.legacy_safety_result = self.safety_guard.evaluate(step11_data)
        action_data: dict[str, Any] = {
            **step11_data,
            **self.legacy_safety_result,
        }
        self.action_controller_result = self.action_controller.evaluate(action_data)
        self._publish_source_data(plan72=plan72, step11_data=step11_data)
        self._schedule_manual_physical_start()

        self._notify()

    def _manual_physical_snapshot(self) -> dict[str, Any]:
        """Build an internal Step15A snapshot without expanding public recorder data."""
        result = self.snapshot()
        result["scheduler_slots"] = (self.scheduler_result or {}).get(
            "scheduler_slots", {}
        )
        return result

    def _read_control_power_setpoint(self) -> float | None:
        """Read the HA control-state used by the frozen Alpha76 power monitor."""
        entity_id = self.control_entity_ids.get("power_setpoint")
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE_SOC_STATES:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    async def _async_verify_platform_setpoint_handoff(
        self, expected_power_w: float
    ) -> bool:
        """Verify that the host integration retained the Alpha76 setpoint write.

        The official Anker control entity may revert a failed write shortly after
        number.set_value returns without surfacing an exception to the caller.
        Alpha76 itself remains unchanged; this DOEMS host adapter only verifies
        that the HA control-state still matches the already-issued source command
        before the normal Alpha76 monitor takes over.
        """
        self._setpoint_handoff_status = "checking"
        self._setpoint_handoff_expected_w = float(expected_power_w)
        self._setpoint_handoff_observed_w = None
        self._setpoint_handoff_samples = []
        self._setpoint_handoff_last_checked_at = dt_util.now().isoformat()

        await asyncio.sleep(_PLATFORM_SETPOINT_HANDOFF_SETTLE_SECONDS)
        all_samples_ok = True
        for index in range(_PLATFORM_SETPOINT_HANDOFF_SAMPLE_COUNT):
            observed = self._read_control_power_setpoint()
            self._setpoint_handoff_samples.append(observed)
            self._setpoint_handoff_observed_w = observed
            if (
                observed is None
                or abs(observed - expected_power_w)
                > _PLATFORM_SETPOINT_HANDOFF_TOLERANCE_W
            ):
                all_samples_ok = False
            if index + 1 < _PLATFORM_SETPOINT_HANDOFF_SAMPLE_COUNT:
                await asyncio.sleep(_PLATFORM_SETPOINT_HANDOFF_SAMPLE_SECONDS)

        self._setpoint_handoff_last_checked_at = dt_util.now().isoformat()
        if all_samples_ok:
            self._setpoint_handoff_status = "confirmed"
            return True

        self._setpoint_handoff_status = "rejected"
        self._setpoint_handoff_failure_count += 1
        return False

    async def async_execute_selected_plan_verified_handoff(self) -> None:
        """Run frozen Alpha76 manual execution plus the canonical host handoff check."""
        data = self.data
        slot = data.get("scheduler_selected_slot")
        detail = ((data.get("scheduler_slots") or {}).get(slot) or
                  (data.get("scheduler_slots") or {}).get(str(slot)) or {})
        try:
            expected_power_w = float(detail.get("power_w"))
        except (TypeError, ValueError) as err:
            raise HomeAssistantError("platform_setpoint_handoff_expected_power_invalid") from err

        await self.execution.async_execute_selected_plan()
        if await self._async_verify_platform_setpoint_handoff(expected_power_w):
            return

        observed = self._setpoint_handoff_observed_w
        reason = (
            "platform_setpoint_handoff_not_confirmed: "
            f"expected={expected_power_w:g}W observed="
            f"{'unavailable' if observed is None else f'{observed:g}W'}"
        )
        await self.execution.async_stop(reason, emergency=True)
        raise HomeAssistantError(reason)

    def _schedule_manual_physical_start(self) -> None:
        """Mirror Alpha76 scheduled-manual and automatic execution listeners."""
        if self._shutdown:
            return
        data = self.data
        if data.get("scheduler_ready") is not True:
            return
        if data.get("scheduler_selected_execution_mode") != "gepland":
            return
        if data.get("scheduler_selected_action") not in {"laden", "ontladen"}:
            return

        slot = data.get("scheduler_selected_slot")
        detail = ((data.get("scheduler_slots") or {}).get(slot) or
                  (data.get("scheduler_slots") or {}).get(str(slot)) or {})
        origin = str(detail.get("origin") or "manual")

        if (
            self.execution.data.get("active")
            or self.execution.data.get("auto_mode_switch_active")
            or self.physical_test.data.get("active")
        ):
            return

        if origin == "automatic_72h_planner":
            if data.get("auto_shadow_execution_permitted") is not True:
                return
            identity = detail.get("planner_identity")
            if not identity:
                return
            if (
                self._automatic_execution_task is not None
                and not self._automatic_execution_task.done()
            ):
                return

            async def _run_automatic() -> None:
                try:
                    await self.execution.async_execute_automatic_plan(str(identity))
                except asyncio.CancelledError:
                    raise
                except HomeAssistantError as err:
                    _LOGGER.warning(
                        "Automatic physical DOEMS execution blocked/failed: %s", err
                    )
                except Exception:
                    _LOGGER.exception(
                        "Unexpected automatic physical DOEMS execution error"
                    )
                finally:
                    self._automatic_execution_task = None
                    if not self._shutdown:
                        self._request_fast_refresh("automatic_execution_terminal")

            self._automatic_execution_task = self.hass.async_create_task(
                _run_automatic(), "DOEMS Alpha76 automatic physical execution"
            )
            return

        if origin != "manual":
            return
        if (
            self._scheduled_manual_start_task is not None
            and not self._scheduled_manual_start_task.done()
        ):
            return

        start_window_end_raw = detail.get("start_window_end")
        start_window_end = (
            dt_util.parse_datetime(str(start_window_end_raw))
            if start_window_end_raw
            else None
        )
        if start_window_end is not None and start_window_end.tzinfo is None:
            start_window_end = start_window_end.replace(
                tzinfo=dt_util.DEFAULT_TIME_ZONE
            )

        retryable_fragments = (
            "Externe modus werd niet tijdig beschikbaar",
            "control_sources_missing",
            "not_in_external_mode",
            "observation_sources_missing",
            "Batterij laadt momenteel; ontladen wordt niet gestart",
            "Batterij ontlaadt momenteel; laden wordt niet gestart",
            "Action Controller niet gereed",
            "platform_setpoint_handoff_not_confirmed",
        )

        async def _run_manual_scheduled() -> None:
            try:
                while True:
                    try:
                        await self.async_execute_selected_plan_verified_handoff()
                        return
                    except HomeAssistantError as err:
                        message = str(err)
                        retryable = any(
                            fragment in message for fragment in retryable_fragments
                        )
                        within_window = bool(
                            start_window_end is not None
                            and dt_util.now() < start_window_end
                        )
                        if not retryable or not within_window:
                            _LOGGER.warning(
                                "Scheduled DOEMS plan %s could not start: %s",
                                slot,
                                err,
                            )
                            return

                        await self.plan_store.async_mark_lifecycle(
                            int(slot),
                            "pending",
                            f"retry_wait: {message}",
                        )
                        await self.async_refresh("scheduled_manual_retry")
                        remaining = max(
                            0.0,
                            (start_window_end - dt_util.now()).total_seconds(),
                        )
                        delay = min(10.0, remaining)
                        if delay <= 0:
                            return
                        await asyncio.sleep(delay)
                        await self.async_refresh("scheduled_manual_retry")
                        current = self.data
                        if (
                            current.get("scheduler_selected_slot") != slot
                            or not current.get("scheduler_ready")
                            or current.get("scheduler_selected_execution_mode") != "gepland"
                        ):
                            return
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception(
                    "Unexpected error while starting scheduled DOEMS plan %s", slot
                )
            finally:
                self._scheduled_manual_start_task = None
                if not self._shutdown:
                    self._request_fast_refresh("scheduled_manual_terminal")

        self._scheduled_manual_start_task = self.hass.async_create_task(
            _run_manual_scheduled(), "DOEMS Alpha76 scheduled plan auto-start"
        )

    @property
    def control_entity_ids(self) -> dict[str, str | None]:
        """Expose the source controller mapping expected by Alpha76 execution."""
        return dict(self.control_path.entity_ids)

    @property
    def data(self) -> dict[str, Any]:
        """Expose the frozen Alpha76 coordinator data contract."""
        return dict(self._source_data_result)

    @property
    def simulation_mode(self) -> bool:
        """Alpha76 manual/test execution requires the normal EMS simulation flag."""
        return True

    @property
    def max_charge_power_w(self) -> int:
        return int(self.settings.max_charge_power_w)

    @property
    def max_discharge_power_w(self) -> int:
        return int(self.settings.max_discharge_power_w)

    def _publish_source_data(
        self,
        *,
        plan72: dict[str, Any],
        step11_data: dict[str, Any],
    ) -> None:
        """Publish the Alpha76 coordinator contract from native DOEMS sources."""
        physical = self.physical_test.data
        execution = self.execution.data
        planner_bundle = self.planner_result or {}
        energy_need = planner_bundle.get("energy_need") or {}
        planner_preview = planner_bundle.get("planner_preview") or {}
        input_result = self.input_result or {}
        forecast_ready = input_result.get("status") == "ready"
        self._source_data_result = {
            **step11_data,
            **energy_need,
            **planner_preview,
            **plan72,
            **self.bridge_result,
            **self.scheduler_result,
            **self.prestart_result,
            **self.safety_result,
            **self.execution_handoff_result,
            **self.final_revalidation_result,
            **self.mode_switch_preview_result,
            **self.automatic_execution_gate_result,
            **self.legacy_safety_result,
            **self.action_controller_result,
            "simulation_mode": True,
            "forecast_ready": forecast_ready,
            "forecast_status": input_result.get("status"),
            "forecast_complete_hours": (
                72 if forecast_ready else sum(
                    1 for row in (input_result.get("rows") or [])
                    if isinstance(row, dict) and row.get("fully_valid")
                )
            ),
            "forecast_home_hours": len(input_result.get("rows") or []),
            "forecast_solar_hours": sum(
                1 for row in (input_result.get("rows") or [])
                if isinstance(row, dict) and row.get("solar_valid")
            ),
            "forecast_price_hours": sum(
                1 for row in (input_result.get("rows") or [])
                if isinstance(row, dict) and row.get("import_price") is not None
            ),
            "forecast_missing_sources": (
                [] if forecast_ready else ["doems_native_forecast_incomplete"]
            ),
            "battery_capacity_kwh": self.settings.battery_capacity_kwh,
            "charge_efficiency_percent": self.settings.charge_efficiency_percent,
            "discharge_efficiency_percent": self.settings.discharge_efficiency_percent,
            "max_charge_power_w": self.settings.max_charge_power_w,
            "max_discharge_power_w": self.settings.max_discharge_power_w,
            "physical_test_active": bool(physical.get("active")),
            "execution_active": bool(execution.get("active")),
            "execution_origin": execution.get("origin"),
            **{f"physical_test_{key}": value for key, value in physical.items()},
            "physical_test_remaining_s": self.physical_test.remaining_seconds,
            **{f"execution_{key}": value for key, value in execution.items()},
            "execution_remaining_s": self.execution.remaining_seconds,
            "auto_bridge_execution_enabled": bool(self._automatic_execution_armed),
        }

    def snapshot(self) -> dict[str, Any]:
        """Return compact entity-safe diagnostics without publishing Plan72 arrays."""
        input_result = self.input_result or {}
        planner = self.planner_result or {}
        need = planner.get("energy_need") or {}
        preview = planner.get("planner_preview") or {}
        plan72 = planner.get("plan72") or {}
        time_contract = input_result.get("time_contract") or {}
        bridge = self.bridge_result or {}
        scheduler = self.scheduler_result or {}
        prestart = self.prestart_result or {}
        safety = self.safety_result or {}
        execution_handoff = self.execution_handoff_result or {}
        final_revalidation = self.final_revalidation_result or {}
        mode_switch_preview = self.mode_switch_preview_result or {}
        automatic_execution_gate = self.automatic_execution_gate_result or {}
        execution = self.execution_result or {}
        legacy_safety = self.legacy_safety_result or {}
        action_controller = self.action_controller_result or {}
        manual_physical = self.execution.data
        control_path = self.control_path_result or {}
        control_entities = control_path.get("entities") or {}
        slots = scheduler.get("scheduler_slots") or {}

        def slot_snapshot(slot: int) -> dict[str, Any]:
            detail = slots.get(slot) or slots.get(str(slot)) or {}
            return {
                "status": detail.get("status"),
                "action": detail.get("action"),
                "purpose": detail.get("purpose"),
                "origin": detail.get("origin"),
                "lifecycle_status": detail.get("lifecycle_status"),
                "start_time": detail.get("start_time"),
                "planned_end_time": detail.get("planned_end_time"),
                "power_w": detail.get("power_w"),
                "planned_energy_kwh": detail.get("planned_energy_kwh"),
                "target_soc": detail.get("target_soc"),
                "selected": detail.get("selected", False),
            }

        return {
            "soc_source_entity": self.soc_entity_id,
            "soc_source_status": self.soc_source_status,
            "soc_percent": self.soc_percent,
            "soc_last_updated": self.soc_last_updated,
            "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None,
            "last_trigger": self.last_trigger,
            "refresh_count": self.refresh_count,
            "last_error": self.last_error,
            "multirate_runtime_version": "alpha21_multirate_runtime_v1",
            "runtime_snapshot_adapter": "alpha33_alpha76_serialized_coordinator_v1",
            "planner_generation": getattr(self, "_planner_generation", 0),
            "planner_published_generation": getattr(
                self, "_planner_published_generation", 0
            ),
            "planner_compute_count": getattr(self, "_planner_compute_count", 0),
            "planner_stale_discard_count": getattr(
                self, "_planner_stale_discard_count", 0
            ),
            "planner_same_signature_skip_count": getattr(
                self, "_planner_same_signature_skip_count", 0
            ),
            "planner_last_input_signature": getattr(
                self, "_planner_last_input_signature", None
            ),
            "planner_last_cycle_id": getattr(
                self, "_planner_last_cycle_id", None
            ),
            "planner_last_refresh": (
                getattr(self, "_planner_last_refresh", None).isoformat()
                if getattr(self, "_planner_last_refresh", None)
                else None
            ),
            "input_source": input_result.get("input_source", "existing_doems_forecast"),
            "input_contract_status": input_result.get("status"),
            "native_expected_slot_count": input_result.get("native_expected_slot_count", 288),
            "native_valid_slot_count": input_result.get("native_valid_slot_count"),
            "transport_row_count": len(input_result.get("rows") or []),
            "alignment_policy": time_contract.get("alignment_policy"),
            "energy_need_status": need.get("energy_need_status"),
            "energy_need_valid": need.get("energy_need_valid"),
            "energy_need_until_solar_kwh": need.get("energy_need_until_solar_kwh"),
            "planner_preview_status": preview.get("planner_preview_status"),
            "planner_preview_decision": preview.get("planner_preview_decision"),
            "planner_preview_reason": preview.get("planner_preview_reason"),
            "plan72_status": plan72.get("auto_plan_72h_status"),
            "plan72_valid": plan72.get("auto_plan_72h_valid"),
            "plan72_count": plan72.get("auto_plan_72h_count"),
            "plan72_start": plan72.get("auto_plan_72h_start"),
            "plan72_end": plan72.get("auto_plan_72h_end"),
            "plan72_start_soc": plan72.get("auto_plan_72h_start_soc"),
            "plan72_end_soc": plan72.get("auto_plan_72h_end_soc"),
            "bridge_status": bridge.get("auto_bridge_status"),
            "bridge_valid": bridge.get("auto_bridge_valid"),
            "bridge_reason": bridge.get("auto_bridge_reason"),
            "bridge_candidate_count": bridge.get("auto_bridge_candidate_count"),
            "bridge_slot_preview_count": bridge.get("auto_bridge_slot_preview_count"),
            "bridge_manual_slot_conflict": bridge.get("auto_bridge_manual_slot_conflict"),
            "plan_store_namespace": f"doems.{self.entry.entry_id}.plans",
            "plan_store_write_gate_open": bridge.get("auto_bridge_plan_store_write_gate_open"),
            "plan_store_write_changed": bridge.get("auto_bridge_plan_store_write_changed"),
            "plan_store_written_slots": bridge.get("auto_bridge_plan_store_written_slots", []),
            "plan_store_cleared_slots": bridge.get("auto_bridge_plan_store_cleared_slots", []),
            "scheduler_status": scheduler.get("scheduler_status"),
            "scheduler_ready": scheduler.get("scheduler_ready"),
            "scheduler_selected_slot": scheduler.get("scheduler_selected_slot"),
            "scheduler_selected_action": scheduler.get("scheduler_selected_action"),
            "scheduler_selected_start_time": scheduler.get("scheduler_selected_start_time"),
            "plan_slot_1": slot_snapshot(1),
            "plan_slot_2": slot_snapshot(2),
            "plan_slot_3": slot_snapshot(3),
            "planner_runtime_active": True,
            "startup_delay_runtime_gate_active": False,
            "plan_store_active": True,
            "scheduler_invoked": bool(self.scheduler_result),
            "prestart_validator_invoked": bool(prestart),
            "prestart_required": prestart.get("auto_prestart_required"),
            "prestart_safe": prestart.get("auto_prestart_safe"),
            "prestart_status": prestart.get("auto_prestart_status"),
            "prestart_reason": prestart.get("auto_prestart_reason"),
            "prestart_reasons": prestart.get("auto_prestart_reasons", []),
            "prestart_warnings": prestart.get("auto_prestart_warnings", []),
            "prestart_selected_slot": prestart.get("auto_prestart_selected_slot"),
            "prestart_planner_identity": prestart.get("auto_prestart_planner_identity"),
            "prestart_identity_match": prestart.get("auto_prestart_current_identity_match"),
            "prestart_signature_match": prestart.get("auto_prestart_current_signature_match"),
            "prestart_current_soc": prestart.get("auto_prestart_current_soc"),
            "prestart_target_soc": prestart.get("auto_prestart_target_soc"),
            "prestart_execution_reserve_soc": prestart.get(
                "auto_prestart_execution_reserve_soc"
            ),
            "prestart_diagnostic_status": prestart.get(
                "auto_prestart_diagnostic_status"
            ),
            "prestart_diagnostic_safe": prestart.get(
                "auto_prestart_diagnostic_safe"
            ),
            "prestart_diagnostic_phase": prestart.get(
                "auto_prestart_diagnostic_phase"
            ),
            "prestart_diagnostic_minutes_to_start": prestart.get(
                "auto_prestart_diagnostic_minutes_to_start"
            ),
            "prestart_diagnostic_live_soc_enforced": prestart.get(
                "auto_prestart_diagnostic_live_soc_enforced"
            ),
            "prestart_diagnostic_blockers": prestart.get(
                "auto_prestart_diagnostic_blockers", []
            ),
            "prestart_diagnostic_warnings": prestart.get(
                "auto_prestart_diagnostic_warnings", []
            ),
            "safety_guard_invoked": bool(safety),
            "safety_handoff_required": safety.get("auto_safety_handoff_required"),
            "safety_handoff_safe": safety.get("auto_safety_handoff_safe"),
            "safety_handoff_status": safety.get("auto_safety_handoff_status"),
            "safety_handoff_reason": safety.get("auto_safety_handoff_reason"),
            "safety_handoff_reasons": safety.get("auto_safety_handoff_reasons", []),
            "safety_handoff_warnings": safety.get("auto_safety_handoff_warnings", []),
            "safety_handoff_selected_slot": safety.get(
                "auto_safety_handoff_selected_slot"
            ),
            "safety_handoff_planner_identity": safety.get(
                "auto_safety_handoff_planner_identity"
            ),
            "safety_handoff_control_path_configured": safety.get(
                "auto_safety_handoff_control_path_configured", False
            ),
            "safety_handoff_execution_permitted": safety.get(
                "auto_safety_handoff_execution_permitted", False
            ),
            "safety_handoff_physical_control": safety.get(
                "auto_safety_handoff_physical_control", False
            ),
            "control_path_configured": bool(control_path.get("configured")),
            "control_path_ready": bool(control_path.get("ready")),
            "control_path_reason": control_path.get("reason"),
            "control_path_stable_seconds": control_path.get("stable_seconds", 0),
            "control_path_required_stable_seconds": control_path.get(
                "required_stable_seconds", 60
            ),
            "control_path_pre_mode_ready": bool(control_path.get("pre_mode_ready")),
            "control_path_pre_mode_reason": control_path.get("pre_mode_reason"),
            "control_path_pre_mode_stable_seconds": control_path.get(
                "pre_mode_stable_seconds", 0
            ),
            "control_path_post_mode_required": bool(
                control_path.get("post_mode_required")
            ),
            "control_path_post_mode_ready": bool(control_path.get("post_mode_ready")),
            "control_path_post_mode_reason": control_path.get("post_mode_reason"),
            "control_path_post_mode_stable_seconds": control_path.get(
                "post_mode_stable_seconds", 0
            ),
            "control_path_operating_mode_entity": control_entities.get(
                "operating_mode", {}
            ).get("entity_id"),
            "control_path_operating_mode": control_entities.get(
                "operating_mode", {}
            ).get("state"),
            "control_path_operating_mode_available": control_entities.get(
                "operating_mode", {}
            ).get("available", False),
            "control_path_action_direction_entity": control_entities.get(
                "action_direction", {}
            ).get("entity_id"),
            "control_path_action_direction": control_entities.get(
                "action_direction", {}
            ).get("state"),
            "control_path_action_direction_available": control_entities.get(
                "action_direction", {}
            ).get("available", False),
            "control_path_power_setpoint_entity": control_entities.get(
                "power_setpoint", {}
            ).get("entity_id"),
            "control_path_power_setpoint": control_entities.get(
                "power_setpoint", {}
            ).get("state"),
            "control_path_power_setpoint_available": control_entities.get(
                "power_setpoint", {}
            ).get("available", False),
            "control_path_read_only": True,
            "execution_handoff_invoked": bool(execution_handoff),
            "execution_handoff_required": execution_handoff.get(
                "auto_execution_handoff_required"
            ),
            "execution_handoff_ready": execution_handoff.get(
                "auto_execution_handoff_ready"
            ),
            "execution_handoff_status": execution_handoff.get(
                "auto_execution_handoff_status"
            ),
            "execution_handoff_reason": execution_handoff.get(
                "auto_execution_handoff_reason"
            ),
            "execution_handoff_reasons": execution_handoff.get(
                "auto_execution_handoff_reasons", []
            ),
            "execution_handoff_warnings": execution_handoff.get(
                "auto_execution_handoff_warnings", []
            ),
            "execution_handoff_selected_slot": execution_handoff.get(
                "auto_execution_handoff_selected_slot"
            ),
            "execution_handoff_planner_identity": execution_handoff.get(
                "auto_execution_handoff_planner_identity"
            ),
            "execution_handoff_action": execution_handoff.get(
                "auto_execution_handoff_action"
            ),
            "execution_handoff_power_w": execution_handoff.get(
                "auto_execution_handoff_power_w"
            ),
            "execution_handoff_target_soc": execution_handoff.get(
                "auto_execution_handoff_target_soc"
            ),
            "execution_handoff_max_runtime_h": execution_handoff.get(
                "auto_execution_handoff_max_runtime_h"
            ),
            "execution_handoff_control_path_configured": execution_handoff.get(
                "auto_execution_handoff_control_path_configured", False
            ),
            "execution_handoff_final_revalidation_required": execution_handoff.get(
                "auto_execution_handoff_final_revalidation_required", True
            ),
            "execution_handoff_execution_permitted": execution_handoff.get(
                "auto_execution_handoff_execution_permitted", False
            ),
            "execution_handoff_physical_control": execution_handoff.get(
                "auto_execution_handoff_physical_control", False
            ),
            "final_revalidation_invoked": bool(final_revalidation),
            "auto_final_revalidation_required": final_revalidation.get("auto_final_revalidation_required"),
            "auto_final_revalidation_safe": final_revalidation.get("auto_final_revalidation_safe"),
            "auto_final_revalidation_status": final_revalidation.get("auto_final_revalidation_status"),
            "auto_final_revalidation_reason": final_revalidation.get("auto_final_revalidation_reason"),
            "auto_final_revalidation_reasons": final_revalidation.get("auto_final_revalidation_reasons", []),
            "auto_final_revalidation_warnings": final_revalidation.get("auto_final_revalidation_warnings", []),
            "auto_final_revalidation_checks": final_revalidation.get("auto_final_revalidation_checks", []),
            "auto_final_revalidation_selected_slot": final_revalidation.get("auto_final_revalidation_selected_slot"),
            "auto_final_revalidation_planner_identity": final_revalidation.get("auto_final_revalidation_planner_identity"),
            "auto_final_revalidation_planner_signature": final_revalidation.get("auto_final_revalidation_planner_signature"),
            "auto_final_revalidation_checked_at": final_revalidation.get("auto_final_revalidation_checked_at"),
            "auto_final_revalidation_action": final_revalidation.get("auto_final_revalidation_action"),
            "auto_final_revalidation_power_w": final_revalidation.get("auto_final_revalidation_power_w"),
            "auto_final_revalidation_target_soc": final_revalidation.get("auto_final_revalidation_target_soc"),
            "auto_final_revalidation_current_soc": final_revalidation.get("auto_final_revalidation_current_soc"),
            "auto_final_revalidation_execution_reserve_soc": final_revalidation.get("auto_final_revalidation_execution_reserve_soc"),
            "auto_final_revalidation_mode_switch_required": final_revalidation.get("auto_final_revalidation_mode_switch_required"),
            "auto_final_revalidation_execution_permitted": False,
            "auto_final_revalidation_physical_control": False,
            "mode_switch_preview_invoked": bool(mode_switch_preview),
            "auto_mode_switch_preview_required": mode_switch_preview.get("auto_mode_switch_preview_required"),
            "auto_mode_switch_preview_ready": mode_switch_preview.get("auto_mode_switch_preview_ready"),
            "auto_mode_switch_preview_status": mode_switch_preview.get("auto_mode_switch_preview_status"),
            "auto_mode_switch_preview_reason": mode_switch_preview.get("auto_mode_switch_preview_reason"),
            "auto_mode_switch_preview_blockers": mode_switch_preview.get("auto_mode_switch_preview_blockers", []),
            "auto_mode_switch_preview_current_mode": mode_switch_preview.get("auto_mode_switch_preview_current_mode"),
            "auto_mode_switch_preview_target_mode": mode_switch_preview.get("auto_mode_switch_preview_target_mode"),
            "auto_mode_switch_preview_switch_required": mode_switch_preview.get("auto_mode_switch_preview_switch_required"),
            "auto_mode_switch_preview_already_external": mode_switch_preview.get("auto_mode_switch_preview_already_external"),
            "auto_mode_switch_preview_action": mode_switch_preview.get("auto_mode_switch_preview_action"),
            "auto_mode_switch_preview_direction": mode_switch_preview.get("auto_mode_switch_preview_direction"),
            "auto_mode_switch_preview_requested_power_w": mode_switch_preview.get("auto_mode_switch_preview_requested_power_w"),
            "auto_mode_switch_preview_zero_power_guard_required": mode_switch_preview.get("auto_mode_switch_preview_zero_power_guard_required"),
            "auto_mode_switch_preview_post_mode_revalidation_required": mode_switch_preview.get("auto_mode_switch_preview_post_mode_revalidation_required"),
            "auto_mode_switch_preview_safe_return_required": mode_switch_preview.get("auto_mode_switch_preview_safe_return_required"),
            "auto_mode_switch_preview_transaction": mode_switch_preview.get("auto_mode_switch_preview_transaction", []),
            "auto_mode_switch_preview_preview_only": True,
            "auto_mode_switch_preview_transaction_started": False,
            "auto_mode_switch_preview_mode_switch_performed": False,
            "auto_mode_switch_preview_direction_written": False,
            "auto_mode_switch_preview_power_setpoint_written": False,
            "auto_mode_switch_preview_execution_controller_released": False,
            "auto_mode_switch_preview_execution_permitted": False,
            "auto_mode_switch_preview_physical_control": False,
            "auto_execution_gate_enabled": automatic_execution_gate.get("auto_execution_gate_enabled", True),
            "auto_execution_gate_status": automatic_execution_gate.get("auto_execution_gate_status", "idle"),
            "auto_execution_gate_technical_ready": automatic_execution_gate.get("auto_execution_gate_technical_ready", False),
            "auto_execution_gate_armed": automatic_execution_gate.get("auto_execution_gate_armed", self._automatic_execution_armed),
            "auto_execution_gate_execution_permitted": automatic_execution_gate.get("auto_execution_gate_execution_permitted", False),
            "auto_execution_gate_selected_slot": automatic_execution_gate.get("auto_execution_gate_selected_slot"),
            "auto_execution_gate_planner_identity": automatic_execution_gate.get("auto_execution_gate_planner_identity"),
            "auto_execution_gate_action": automatic_execution_gate.get("auto_execution_gate_action"),
            "auto_execution_gate_purpose": automatic_execution_gate.get("auto_execution_gate_purpose"),
            "auto_execution_gate_power_w": automatic_execution_gate.get("auto_execution_gate_power_w"),
            "auto_execution_gate_target_soc": automatic_execution_gate.get("auto_execution_gate_target_soc"),
            "auto_execution_gate_max_runtime_h": automatic_execution_gate.get("auto_execution_gate_max_runtime_h"),
            "auto_execution_gate_price_sources": automatic_execution_gate.get("auto_execution_gate_price_sources", []),
            "auto_execution_gate_all_prices_known": automatic_execution_gate.get("auto_execution_gate_all_prices_known", False),
            "auto_execution_gate_safety_recovery_exception": automatic_execution_gate.get("auto_execution_gate_safety_recovery_exception", False),
            "auto_execution_gate_execution_buffer_safe": automatic_execution_gate.get("auto_execution_gate_execution_buffer_safe", False),
            "auto_execution_gate_manual_override_active": automatic_execution_gate.get("auto_execution_gate_manual_override_active", False),
            "auto_execution_gate_blockers": automatic_execution_gate.get("auto_execution_gate_blockers", []),
            "auto_execution_gate_warnings": automatic_execution_gate.get("auto_execution_gate_warnings", []),
            "auto_execution_gate_checks": automatic_execution_gate.get("auto_execution_gate_checks", []),
            **execution,
            "execution_store_status": self.execution_store_status,
            "execution_store_error": self.execution_store_error,
            "execution_store_last_saved_at": self.execution_store_last_saved_at,
            "execution_store_key": f"{DOMAIN}.{self.entry.entry_id}.execution",
            "execution_store_restart_policy": "alpha76_interrupted_run_safe_stop_arm_restored_separately",
            "legacy_safety_status": legacy_safety.get("safety_status"),
            "legacy_safety_safe": legacy_safety.get("safety_safe"),
            "legacy_safety_reason": legacy_safety.get("safety_reason"),
            "action_controller_invoked": bool(action_controller),
            "controller_status": action_controller.get("controller_status"),
            "controller_ready": action_controller.get("controller_ready"),
            "controller_selected_slot": action_controller.get(
                "controller_selected_slot"
            ),
            "controller_action": action_controller.get("controller_action"),
            "controller_power_w": action_controller.get("controller_power_w"),
            "controller_target_soc": action_controller.get("controller_target_soc"),
            "controller_max_runtime_h": action_controller.get(
                "controller_max_runtime_h"
            ),
            "controller_execution_mode": action_controller.get(
                "controller_execution_mode"
            ),
            "controller_reason": action_controller.get("controller_reason"),
            "controller_desired_mode": action_controller.get(
                "controller_desired_mode"
            ),
            "controller_desired_direction": action_controller.get(
                "controller_desired_direction"
            ),
            "controller_desired_power_w": action_controller.get(
                "controller_desired_power_w"
            ),
            "controller_physical_control": action_controller.get(
                "controller_physical_control", False
            ),
            "execution_controller_invoked": bool(manual_physical.get("active")),
            "execution_mode": "live_guarded" if self._automatic_execution_armed else "disarmed",
            "automatic_execution_armed": self._automatic_execution_armed,
            "manual_physical_execution_enabled": True,
            "manual_physical_execution_active": bool(manual_physical.get("active")),
            "manual_physical_execution_busy": bool(manual_physical.get("busy")),
            "manual_physical_execution_status": manual_physical.get("status"),
            "manual_physical_execution_reason": manual_physical.get("reason"),
            "manual_physical_execution_slot": manual_physical.get("slot"),
            "manual_physical_execution_action": manual_physical.get("action"),
            "manual_physical_execution_power_w": manual_physical.get("power_w"),
            "manual_physical_execution_target_soc": manual_physical.get("target_soc"),
            "manual_physical_safe_return_performed": manual_physical.get(
                "safe_return_performed", False
            ),
            "manual_physical_write_count": 0,
            "physical_execution_origin": manual_physical.get("origin"),
            "physical_execution_planner_identity": manual_physical.get("planner_identity"),
            "physical_execution_planner_signature": manual_physical.get("planner_signature"),
            "physical_execution_active": bool(manual_physical.get("active")),
            "physical_execution_busy": bool(manual_physical.get("busy")),
            "physical_execution_status": manual_physical.get("status"),
            "physical_execution_reason": manual_physical.get("reason"),
            "physical_execution_slot": manual_physical.get("slot"),
            "physical_execution_action": manual_physical.get("action"),
            "physical_execution_power_w": manual_physical.get("power_w"),
            "physical_execution_target_soc": manual_physical.get("target_soc"),
            "physical_execution_safe_return_performed": manual_physical.get(
                "safe_return_performed", False
            ),
            "physical_execution_write_count": 0,
            "automatic_planner_physical_execution_enabled": True,
            "service_calls_performed": bool(
                manual_physical.get("active")
                or manual_physical.get("last_result") is not None
            ),
            "physical_execution_authority": bool(
                manual_physical.get("active")
                or manual_physical.get("auto_mode_switch_active")
            ),
        }
