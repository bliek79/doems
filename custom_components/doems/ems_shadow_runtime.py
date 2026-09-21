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

from .const import (
    CONF_SOC_ENTITY,
    CONF_DEVICE_STATUS_ENTITY,
    CONF_CHARGE_POWER_ENTITY,
    CONF_DISCHARGE_POWER_ENTITY,
    CONF_OPERATING_MODE_ENTITY,
    CONF_ACTION_DIRECTION_ENTITY,
    CONF_POWER_SETPOINT_ENTITY,
)
from .ems_alpha76_adapter import run_shadow_chain
from .ems_alpha76.plan_store import DOEMSShadowPlanStore
from .ems_alpha76.scheduler import DOEMSShadowScheduler
from .ems_alpha76.planner_action_bridge import build_planner_action_bridge
from .ems_alpha76.prestart_validator import AnkerEmsPreStartValidator
from .ems_alpha76.safety_guard import AnkerEmsSafetyGuard
from .ems_alpha76.action_controller import AnkerEmsActionController
from .ems_alpha76.execution_shadow import DOEMSShadowExecutionGates
from .ems_alpha76.automatic_execution_shadow import build_automatic_execution_shadow
from .ems_live_input import build_live_ems_input
from .energy_sources import normalize_power_w
from .ems_settings import EMSSettings
from .ems_soc import UNAVAILABLE_SOC_STATES, parse_soc_percent
from .ems_step5b import ExecutionEnvelope, build_execution_envelope, build_step5b_rehearsal


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
        self.downstream_result: dict[str, Any] = {}
        self.step5b_result: dict[str, Any] = {}
        self.step5b_envelope: ExecutionEnvelope | None = None
        self.prestart = AnkerEmsPreStartValidator()
        self.safety_guard = AnkerEmsSafetyGuard()
        self.action_controller = AnkerEmsActionController()
        self.execution_gates = DOEMSShadowExecutionGates()

        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._refresh_pending = False
        self._shutdown = False

    @property
    def soc_entity_id(self) -> str | None:
        value = self.entry.options.get(CONF_SOC_ENTITY)
        return str(value) if value else None

    @property
    def observation_entity_ids(self) -> list[str]:
        keys = (
            CONF_DEVICE_STATUS_ENTITY,
            CONF_CHARGE_POWER_ENTITY,
            CONF_DISCHARGE_POWER_ENTITY,
            CONF_OPERATING_MODE_ENTITY,
            CONF_ACTION_DIRECTION_ENTITY,
            CONF_POWER_SETPOINT_ENTITY,
        )
        return [
            str(self.entry.options[key])
            for key in keys
            if self.entry.options.get(key)
        ]

    def _state_value(self, key: str) -> str | None:
        entity_id = self.entry.options.get(key)
        if not entity_id:
            return None
        state = self.hass.states.get(str(entity_id))
        if state is None or state.state in {"unknown", "unavailable", "none", "None", ""}:
            return None
        return str(state.state)

    def _power_value(self, key: str) -> float | None:
        entity_id = self.entry.options.get(key)
        if not entity_id:
            return None
        state = self.hass.states.get(str(entity_id))
        if state is None:
            return None
        unit = state.attributes.get("unit_of_measurement")
        return normalize_power_w(state.state, unit, allow_negative=False)

    def _number_value(self, key: str) -> float | None:
        entity_id = self.entry.options.get(key)
        if not entity_id:
            return None
        state = self.hass.states.get(str(entity_id))
        if state is None or state.state in {"unknown", "unavailable", "none", "None", ""}:
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        unit = state.attributes.get("unit_of_measurement")
        if unit == "kW":
            value *= 1000.0
        return value

    def _observation_source_status(
        self,
        key: str,
        *,
        kind: str,
    ) -> dict[str, Any]:
        """Return one compact read-only observation-source diagnostic."""
        entity_id = self.entry.options.get(key)
        if not entity_id:
            return {
                "entity_id": None,
                "configured": False,
                "available": False,
                "valid": False,
                "status": "not_configured",
                "value": None,
            }
        entity_id = str(entity_id)
        state = self.hass.states.get(entity_id)
        if state is None:
            return {
                "entity_id": entity_id,
                "configured": True,
                "available": False,
                "valid": False,
                "status": "entity_missing",
                "value": None,
            }
        if state.state in {"unknown", "unavailable", "none", "None", ""}:
            return {
                "entity_id": entity_id,
                "configured": True,
                "available": False,
                "valid": False,
                "status": "unavailable",
                "value": None,
            }

        if kind == "power":
            value = normalize_power_w(
                state.state,
                state.attributes.get("unit_of_measurement"),
                allow_negative=False,
            )
        elif kind == "number":
            try:
                value = float(state.state)
            except (TypeError, ValueError):
                value = None
            if value is not None and state.attributes.get("unit_of_measurement") == "kW":
                value *= 1000.0
        else:
            value = str(state.state)

        valid = value is not None
        return {
            "entity_id": entity_id,
            "configured": True,
            "available": True,
            "valid": valid,
            "status": "ok" if valid else "invalid_value",
            "value": value,
        }

    def _observation_contract(self) -> dict[str, Any]:
        """Build the central Step 5A observation-completeness contract."""
        sources = {
            "device_status": self._observation_source_status(
                CONF_DEVICE_STATUS_ENTITY, kind="state"
            ),
            "charge_power": self._observation_source_status(
                CONF_CHARGE_POWER_ENTITY, kind="power"
            ),
            "discharge_power": self._observation_source_status(
                CONF_DISCHARGE_POWER_ENTITY, kind="power"
            ),
            "operating_mode": self._observation_source_status(
                CONF_OPERATING_MODE_ENTITY, kind="state"
            ),
            "action_direction": self._observation_source_status(
                CONF_ACTION_DIRECTION_ENTITY, kind="state"
            ),
            "power_setpoint": self._observation_source_status(
                CONF_POWER_SETPOINT_ENTITY, kind="number"
            ),
        }

        configured = [name for name, item in sources.items() if item["configured"]]
        valid = [name for name, item in sources.items() if item["valid"]]
        missing = [name for name, item in sources.items() if not item["configured"]]
        unavailable = [
            name
            for name, item in sources.items()
            if item["configured"] and not item["available"]
        ]
        invalid = [
            name
            for name, item in sources.items()
            if item["available"] and not item["valid"]
        ]

        mode = sources["operating_mode"]
        direction = sources["action_direction"]
        setpoint = sources["power_setpoint"]

        pre_mode_ready = bool(mode["valid"])
        post_mode_required = mode.get("value") == "third_party_control"
        post_mode_ready = bool(direction["valid"] and setpoint["valid"])
        control_path_configured = bool(
            mode["configured"] and direction["configured"] and setpoint["configured"]
        )

        if len(valid) == len(sources):
            status = "ready"
        elif not configured:
            status = "not_configured"
        else:
            status = "partial"

        return {
            "observation_contract_status": status,
            "observation_expected_source_count": len(sources),
            "observation_configured_source_count": len(configured),
            "observation_valid_source_count": len(valid),
            "observation_missing_sources": missing,
            "observation_unavailable_sources": unavailable,
            "observation_invalid_sources": invalid,
            "observation_sources": sources,
            "control_path_configured": control_path_configured,
            "control_path_pre_mode_ready": pre_mode_ready,
            "control_path_post_mode_required": post_mode_required,
            "control_path_post_mode_ready": post_mode_ready,
        }

    def _control_path_readiness(self) -> dict[str, Any]:
        """Mirror Alpha76 two-stage 60-second control-path stability."""
        required_stable_seconds = 60.0
        now = self.last_refresh or dt_util.utcnow()

        def detail(key: str) -> dict[str, Any]:
            entity_id = self.entry.options.get(key)
            if not entity_id:
                return {
                    "entity_id": None,
                    "available": False,
                    "state": None,
                    "stable_seconds": 0.0,
                }
            entity_id = str(entity_id)
            state = self.hass.states.get(entity_id)
            available = (
                state is not None
                and state.state not in {"unknown", "unavailable", "none", "None", ""}
            )
            stable_seconds = 0.0
            if available and state is not None:
                stable_seconds = max(
                    0.0,
                    (now - state.last_changed).total_seconds(),
                )
            return {
                "entity_id": entity_id,
                "available": available,
                "state": None if state is None else state.state,
                "stable_seconds": round(stable_seconds, 1),
            }

        mode = detail(CONF_OPERATING_MODE_ENTITY)
        direction = detail(CONF_ACTION_DIRECTION_ENTITY)
        power = detail(CONF_POWER_SETPOINT_ENTITY)
        entities = {
            "operating_mode": mode,
            "action_direction": direction,
            "power_setpoint": power,
        }

        pre_blockers: list[str] = []
        if not mode["available"]:
            pre_blockers.append("operating_mode_unavailable")
        elif mode["stable_seconds"] < required_stable_seconds:
            pre_blockers.append("operating_mode_not_stable")
        pre_mode_ready = not pre_blockers
        pre_mode_reason = "pre_mode_ready" if pre_mode_ready else ",".join(pre_blockers)
        pre_mode_stable = mode["stable_seconds"] if mode["available"] else 0.0

        external_active = mode["available"] and mode["state"] == "third_party_control"
        post_blockers: list[str] = []
        if not external_active:
            post_mode_ready = False
            post_mode_reason = "awaiting_third_party_control"
            post_mode_stable = 0.0
        else:
            for name, item in (
                ("action_direction", direction),
                ("power_setpoint", power),
            ):
                if not item["available"]:
                    post_blockers.append(f"{name}_unavailable")
                elif item["stable_seconds"] < required_stable_seconds:
                    post_blockers.append(f"{name}_not_stable")
            post_mode_ready = not post_blockers
            post_mode_reason = (
                "post_mode_ready" if post_mode_ready else ",".join(post_blockers)
            )
            post_mode_stable = (
                min(direction["stable_seconds"], power["stable_seconds"])
                if direction["available"] and power["available"]
                else 0.0
            )

        ready = pre_mode_ready and (post_mode_ready if external_active else True)
        reason = (
            "control_path_ready"
            if ready
            else (post_mode_reason if external_active else pre_mode_reason)
        )
        stable_seconds = post_mode_stable if external_active else pre_mode_stable

        return {
            "ready": ready,
            "reason": reason,
            "stable_seconds": round(stable_seconds, 1),
            "required_stable_seconds": required_stable_seconds,
            "pre_mode_ready": pre_mode_ready,
            "pre_mode_reason": pre_mode_reason,
            "pre_mode_stable_seconds": round(pre_mode_stable, 1),
            "post_mode_ready": post_mode_ready,
            "post_mode_reason": post_mode_reason,
            "post_mode_stable_seconds": round(post_mode_stable, 1),
            "post_mode_required": external_active,
            "entities": entities,
        }

    def _observation_snapshot(self) -> dict[str, Any]:
        contract = self._observation_contract()
        control_path_configured = contract["control_path_configured"]
        return {
            **contract,
            "device_status": self._state_value(CONF_DEVICE_STATUS_ENTITY),
            "charge_power_w": self._power_value(CONF_CHARGE_POWER_ENTITY),
            "discharge_power_w": self._power_value(CONF_DISCHARGE_POWER_ENTITY),
            "operating_mode": self._state_value(CONF_OPERATING_MODE_ENTITY),
            "action_direction": self._state_value(CONF_ACTION_DIRECTION_ENTITY),
            "power_setpoint_w": self._number_value(CONF_POWER_SETPOINT_ENTITY),
            "control_path_configured": control_path_configured,
            "physical_test_active": False,
            "execution_active": False,
            "simulation_mode": True,
        }

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

        observation_ids = self.observation_entity_ids
        if observation_ids:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    observation_ids,
                    self._observation_state_changed,
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
    def _observation_state_changed(self, _event: Event[EventStateChangedData]) -> None:
        self._request_refresh("ems_observation_state_change")

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
        self.downstream_result = {}
        self.step5b_result = {}

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
            "soc": self.soc_percent,
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
        self._run_downstream_shadow({**refreshed_data, **self.bridge_result})

    def _run_downstream_shadow(self, data: dict[str, Any]) -> None:
        """Run frozen downstream gates in Alpha76 order without actuation."""
        work = {
            **data,
            **self.bridge_result,
            **self._observation_snapshot(),
            "soc": self.soc_percent,
            "forecast_ready": True,
        }
        work.update(self.prestart.evaluate(work))
        work.update(self.safety_guard.evaluate_automatic_handoff(work))
        work.update(self.execution_gates.evaluate_automatic_handoff(work))
        work.update(self.execution_gates.evaluate_final_revalidation(work))
        work.update(self.execution_gates.evaluate_mode_switch_transaction(work))
        readiness = self._control_path_readiness()
        work.update(
            build_automatic_execution_shadow(
                work,
                readiness=readiness,
                armed=False,
            )
        )

        captured, _capture_blockers, _capture_warnings = build_execution_envelope(work)
        if self.step5b_envelope is None and captured is not None:
            self.step5b_envelope = captured

        self.step5b_result = build_step5b_rehearsal(
            work,
            previous_envelope=self.step5b_envelope,
        )
        if self.step5b_result.get("step5b_status") == "aborted_disarmed":
            # Preserve this refresh's abort diagnostics, but require a fresh
            # full Step 5A validation before a new envelope may be captured.
            self.step5b_envelope = None
        work.update(self.step5b_result)

        work.update(self.safety_guard.evaluate(work))
        work.update(self.action_controller.evaluate(work))
        self.downstream_result = work

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
        downstream = self.downstream_result or {}
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
            "invalid_slot_count": input_result.get("invalid_slot_count"),
            "first_invalid_slot": input_result.get("first_invalid_slot"),
            "last_invalid_slot": input_result.get("last_invalid_slot"),
            "invalid_slots": input_result.get("invalid_slots", []),
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
            "shadow_prestart_diagnostic_status": downstream.get("auto_prestart_diagnostic_status"),
            "shadow_prestart_diagnostic_phase": downstream.get("auto_prestart_diagnostic_phase"),
            "shadow_prestart_diagnostic_safe": downstream.get("auto_prestart_diagnostic_safe"),
            "shadow_prestart_minutes_to_start": downstream.get("auto_prestart_diagnostic_minutes_to_start"),
            "shadow_prestart_status": downstream.get("auto_prestart_status"),
            "shadow_prestart_required": downstream.get("auto_prestart_required"),
            "shadow_prestart_safe": downstream.get("auto_prestart_safe"),
            "shadow_prestart_reasons": downstream.get("auto_prestart_reasons", []),
            "shadow_prestart_warnings": downstream.get("auto_prestart_warnings", []),
            "shadow_safety_handoff_status": downstream.get("auto_safety_handoff_status"),
            "shadow_safety_handoff_required": downstream.get("auto_safety_handoff_required"),
            "shadow_safety_handoff_safe": downstream.get("auto_safety_handoff_safe"),
            "shadow_safety_handoff_reasons": downstream.get("auto_safety_handoff_reasons", []),
            "shadow_execution_handoff_status": downstream.get("auto_execution_handoff_status"),
            "shadow_execution_handoff_required": downstream.get("auto_execution_handoff_required"),
            "shadow_execution_handoff_ready": downstream.get("auto_execution_handoff_ready"),
            "shadow_execution_handoff_reasons": downstream.get("auto_execution_handoff_reasons", []),
            "shadow_final_revalidation_status": downstream.get("auto_final_revalidation_status"),
            "shadow_final_revalidation_required": downstream.get("auto_final_revalidation_required"),
            "shadow_final_revalidation_safe": downstream.get("auto_final_revalidation_safe"),
            "shadow_final_revalidation_reasons": downstream.get("auto_final_revalidation_reasons", []),
            "shadow_mode_switch_preview_status": downstream.get("auto_mode_switch_preview_status"),
            "shadow_mode_switch_preview_required": downstream.get("auto_mode_switch_preview_required"),
            "shadow_mode_switch_preview_ready": downstream.get("auto_mode_switch_preview_ready"),
            "shadow_mode_switch_preview_blockers": downstream.get("auto_mode_switch_preview_blockers", []),
            "shadow_auto_execution_status": downstream.get("auto_shadow_status"),
            "shadow_auto_execution_technical_ready": downstream.get("auto_shadow_technical_ready"),
            "shadow_auto_execution_armed": downstream.get("auto_shadow_armed", False),
            "shadow_auto_execution_permitted": downstream.get("auto_shadow_execution_permitted", False),
            "shadow_auto_execution_selected_slot": downstream.get("auto_shadow_selected_slot"),
            "shadow_auto_execution_action": downstream.get("auto_shadow_action"),
            "shadow_auto_execution_purpose": downstream.get("auto_shadow_purpose"),
            "shadow_auto_execution_power_w": downstream.get("auto_shadow_power_w"),
            "shadow_auto_execution_target_soc": downstream.get("auto_shadow_target_soc"),
            "shadow_auto_execution_start_time": downstream.get("auto_shadow_start_time"),
            "shadow_auto_execution_blockers": downstream.get("auto_shadow_blockers", []),
            "shadow_auto_execution_warnings": downstream.get("auto_shadow_warnings", []),
            "shadow_control_path_ready": downstream.get("auto_shadow_control_path_ready"),
            "shadow_control_path_reason": downstream.get("auto_shadow_control_path_reason"),
            "shadow_control_path_stable_seconds": downstream.get("auto_shadow_control_path_stable_seconds"),
            "shadow_control_path_required_stable_seconds": downstream.get("auto_shadow_control_path_required_stable_seconds"),
            "shadow_control_path_pre_mode_reason": downstream.get("auto_shadow_pre_mode_reason"),
            "shadow_control_path_pre_mode_stable_seconds": downstream.get("auto_shadow_pre_mode_stable_seconds"),
            "shadow_control_path_post_mode_reason": downstream.get("auto_shadow_post_mode_reason"),
            "shadow_control_path_post_mode_stable_seconds": downstream.get("auto_shadow_post_mode_stable_seconds"),
            "shadow_legacy_safety_status": downstream.get("safety_status"),
            "shadow_action_controller_status": downstream.get("controller_status"),
            "shadow_action_controller_ready": downstream.get("controller_ready"),
            "shadow_observation_contract_status": downstream.get("observation_contract_status"),
            "shadow_observation_expected_source_count": downstream.get("observation_expected_source_count"),
            "shadow_observation_configured_source_count": downstream.get("observation_configured_source_count"),
            "shadow_observation_valid_source_count": downstream.get("observation_valid_source_count"),
            "shadow_observation_missing_sources": downstream.get("observation_missing_sources", []),
            "shadow_observation_unavailable_sources": downstream.get("observation_unavailable_sources", []),
            "shadow_observation_invalid_sources": downstream.get("observation_invalid_sources", []),
            "shadow_observation_device_status": (downstream.get("observation_sources") or {}).get("device_status"),
            "shadow_observation_charge_power": (downstream.get("observation_sources") or {}).get("charge_power"),
            "shadow_observation_discharge_power": (downstream.get("observation_sources") or {}).get("discharge_power"),
            "shadow_observation_operating_mode": (downstream.get("observation_sources") or {}).get("operating_mode"),
            "shadow_observation_action_direction": (downstream.get("observation_sources") or {}).get("action_direction"),
            "shadow_observation_power_setpoint": (downstream.get("observation_sources") or {}).get("power_setpoint"),
            "shadow_control_path_configured": downstream.get("control_path_configured"),
            "shadow_control_path_pre_mode_ready": downstream.get("control_path_pre_mode_ready"),
            "shadow_control_path_post_mode_required": downstream.get("control_path_post_mode_required"),
            "shadow_control_path_post_mode_ready": downstream.get("control_path_post_mode_ready"),
            "shadow_operating_mode": downstream.get("operating_mode"),
            "shadow_charge_power_w": downstream.get("charge_power_w"),
            "shadow_discharge_power_w": downstream.get("discharge_power_w"),
            "shadow_power_setpoint_w": downstream.get("power_setpoint_w"),
            "step5b_status": downstream.get("step5b_status"),
            "step5b_envelope_ready": downstream.get("step5b_envelope_ready", False),
            "step5b_envelope_fingerprint": downstream.get("step5b_envelope_fingerprint"),
            "step5b_envelope": downstream.get("step5b_envelope"),
            "step5b_transaction_phase": downstream.get("step5b_transaction_phase"),
            "step5b_transaction_ready": downstream.get("step5b_transaction_ready", False),
            "step5b_rehearsal_phases": downstream.get("step5b_rehearsal_phases", []),
            "step5b_blockers": downstream.get("step5b_blockers", []),
            "step5b_warnings": downstream.get("step5b_warnings", []),
            "step5b_abort_reason": downstream.get("step5b_abort_reason"),
            "step5b_authority_fence": False,
            "step5b_service_calls_performed": False,
            "shadow_planner_runtime_active": True,
            "startup_delay_runtime_gate_active": False,
            "shadow_plan_store_active": True,
            "scheduler_invoked": bool(self.scheduler_result),
            "prestart_validator_invoked": bool(self.downstream_result),
            "safety_guard_invoked": bool(self.downstream_result),
            "action_controller_invoked": bool(self.downstream_result),
            "execution_controller_invoked": bool(self.downstream_result),
            "automatic_execution_armed": False,
            "mode_switch_service_calls_available": False,
            "service_calls_performed": False,
            "physical_execution_authority": False,
        }
