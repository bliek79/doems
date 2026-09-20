"""Live read-only G6 Step 5A EMS shadow runtime.

Consumes the existing DOEMS forecast stack plus one configured SOC sensor and
invokes the frozen Alpha76 shadow decision chain. This runtime owns no plan
store, scheduler, controller, service call or physical execution authority.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import CONF_SOC_ENTITY
from .ems_alpha76_adapter import run_shadow_chain
from .ems_alpha76.plan_store import DOEMSShadowPlanStore
from .ems_alpha76.scheduler import DOEMSShadowScheduler
from .ems_alpha76.planner_action_bridge import build_planner_action_bridge
from .ems_live_input import build_live_ems_input
from .ems_settings import EMSSettings
from .ems_soc import UNAVAILABLE_SOC_STATES, parse_soc_percent


class DOEMSEMSShadowRuntime:
    """Read-only live invocation layer for the copied Alpha76 shadow chain."""

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
        self.shadow_result: dict[str, Any] | None = None
        self.soc_percent: float | None = None
        self.soc_source_status = "not_configured"
        self.soc_last_updated: str | None = None
        self.plan_store = DOEMSShadowPlanStore(hass, entry.entry_id)
        self.scheduler = DOEMSShadowScheduler(self.plan_store)
        self.bridge_result: dict[str, Any] = {}
        self.scheduler_result: dict[str, Any] = {}
        self.plan_store_result: dict[str, Any] = {}
        self.handoff_result: dict[str, Any] = {}
        self.expired_release_result: dict[str, Any] = {}

        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._refresh_pending = False
        self._shutdown = False

    @property
    def soc_entity_id(self) -> str | None:
        value = self.entry.options.get(CONF_SOC_ENTITY)
        return str(value) if value else None

    async def async_setup(self) -> None:
        """Load shadow plans, attach read-only listeners and perform first refresh."""
        await self.plan_store.async_load()
        for source, trigger in (
            (self.coordinator, "energy_forecast_update"),
            (self.solar_forecast, "solar_forecast_update"),
            (self.prices, "prices_forecast_update"),
        ):
            if source is not None and hasattr(source, "async_add_listener"):
                self._unsubs.append(
                    source.async_add_listener(
                        lambda trigger=trigger: self._request_refresh(trigger)
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

        await self.async_refresh("startup")

    async def async_shutdown(self) -> None:
        self._shutdown = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._listeners.clear()

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
    def _soc_state_changed(self, _event: Event[EventStateChangedData]) -> None:
        self._request_refresh("soc_state_change")

    @callback
    def _request_refresh(self, trigger: str) -> None:
        if self._shutdown or self._refresh_pending:
            return
        self._refresh_pending = True
        self.hass.async_create_task(self._async_requested_refresh(trigger))

    async def _async_requested_refresh(self, trigger: str) -> None:
        await asyncio.sleep(0)
        self._refresh_pending = False
        if not self._shutdown:
            await self.async_refresh(trigger)

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

    async def async_refresh(self, trigger: str) -> None:
        """Recalculate shadow diagnostics only; never actuate anything."""
        self.last_trigger = trigger
        self.last_refresh = dt_util.utcnow()
        self.refresh_count += 1
        self.last_error = None
        self.input_result = None
        self.shadow_result = None
        self.bridge_result = {}
        self.scheduler_result = {}
        self.plan_store_result = {}
        self.handoff_result = {}
        self.expired_release_result = {}

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
                reference=self.last_refresh,
            )
            self.input_result = input_result
            if (
                input_result.get("status") != "ready"
                or input_result.get("native_valid_slot_count") != 288
                or len(input_result.get("rows") or []) != 72
            ):
                self.status = "waiting_for_complete_forecast"
                self._notify()
                return

            self.shadow_result = run_shadow_chain(
                input_result=input_result,
                settings=self.settings,
                soc_percent=soc,
                now=self.last_refresh,
            )
            await self._async_run_bridge_planstore_scheduler()
            self.status = "ready"
        except Exception as err:
            self.status = "error"
            self.last_error = f"{type(err).__name__}: {err}"

        self._notify()

    async def _async_run_bridge_planstore_scheduler(self) -> None:
        """Mirror the frozen Alpha76 Bridge -> Plan Store -> Scheduler shadow chain."""
        shadow = self.shadow_result or {}
        plan72 = dict(shadow.get("plan72") or {})
        data: dict[str, Any] = {
            **plan72,
            "forecast_ready": True,
            "max_charge_power_w": self.settings.max_charge_power_w,
            "max_discharge_power_w": self.settings.max_discharge_power_w,
            "battery_capacity_kwh": self.settings.battery_capacity_kwh,
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

    def snapshot(self) -> dict[str, Any]:
        """Return compact entity-safe diagnostics without publishing Plan72 arrays."""
        input_result = self.input_result or {}
        shadow = self.shadow_result or {}
        need = shadow.get("energy_need") or {}
        preview = shadow.get("planner_preview") or {}
        plan72 = shadow.get("plan72") or {}
        time_contract = input_result.get("time_contract") or {}
        bridge = self.bridge_result or {}
        scheduler = self.scheduler_result or {}
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
            "shadow_plan_store_namespace": f"doems.{self.entry.entry_id}.shadow_plans",
            "shadow_plan_store_write_gate_open": bridge.get("auto_bridge_plan_store_write_gate_open"),
            "shadow_plan_store_write_changed": bridge.get("auto_bridge_plan_store_write_changed"),
            "shadow_plan_store_written_slots": bridge.get("auto_bridge_plan_store_written_slots", []),
            "shadow_plan_store_cleared_slots": bridge.get("auto_bridge_plan_store_cleared_slots", []),
            "shadow_scheduler_status": scheduler.get("scheduler_status"),
            "shadow_scheduler_ready": scheduler.get("scheduler_ready"),
            "shadow_scheduler_selected_slot": scheduler.get("scheduler_selected_slot"),
            "shadow_scheduler_selected_action": scheduler.get("scheduler_selected_action"),
            "shadow_scheduler_selected_start_time": scheduler.get("scheduler_selected_start_time"),
            "shadow_slot_1": slot_snapshot(1),
            "shadow_slot_2": slot_snapshot(2),
            "shadow_slot_3": slot_snapshot(3),
            "shadow_planner_runtime_active": True,
            "startup_delay_runtime_gate_active": False,
            "shadow_plan_store_active": True,
            "scheduler_invoked": bool(self.scheduler_result),
            "prestart_validator_invoked": False,
            "safety_guard_invoked": False,
            "action_controller_invoked": False,
            "execution_controller_invoked": False,
            "service_calls_performed": False,
            "physical_execution_authority": False,
        }
