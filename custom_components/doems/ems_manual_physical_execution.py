"""Step 15 guarded physical execution for Scheduler-selected DOEMS plans.

This remains the single actuating DOEMS path. Beta phase 2 keeps the proven
manual execution sequence unchanged and additionally permits a Scheduler-selected
origin=automatic_72h_planner plan only when the existing Automatic Execution
Gate is armed_ready and execution_permitted. No planner policy is implemented
or recalculated in this module.

The controller copies the proven Anker EMS execution sequence:
self_consumption -> third_party_control -> zero-power guard -> stable controls
-> safety recheck -> direction/power handoff -> runtime monitoring -> 0 W ->
self_consumption.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_CHARGE_POWER_ENTITY,
    CONF_BATTERY_DISCHARGE_POWER_ENTITY,
    CONF_DEVICE_STATUS_ENTITY,
    CONF_SOC_ENTITY,
    DOMAIN,
)
from .energy_sources import normalize_power_w
from .ems_plan_store import DOEMSPlanStore
from .ems_settings import EMSSettings
from .ems_soc import UNAVAILABLE_SOC_STATES, parse_soc_percent

_LOGGER = logging.getLogger(__name__)

_EXTERNAL_MODE = "third_party_control"
_SELF_MODE = "self_consumption"
_CONTROL_STABLE_SECONDS = 60
_CONTROL_WAIT_SECONDS = 90
_MONITOR_INTERVAL_SECONDS = 5
_STORAGE_VERSION = 1
_POWER_TOLERANCE_W = 25.0


class DOEMSManualPhysicalExecution:
    """Execute one guarded Scheduler-selected planslot behind the explicit DOEMS arm."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        plan_store: DOEMSPlanStore,
        settings: EMSSettings,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.plan_store = plan_store
        self.settings = settings
        self._store: Store[dict[str, Any]] = Store(
            hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.manual_physical_execution",
        )
        self._monitor_task: asyncio.Task[None] | None = None
        self._armed_provider: Callable[[], bool] | None = None
        self._state: dict[str, Any] = {
            "active": False,
            "status": "idle",
            "reason": "Geen fysieke handmatige DOEMS-uitvoering actief",
            "slot": None,
            "action": None,
            "origin": None,
            "planner_identity": None,
            "planner_signature": None,
            "power_w": None,
            "target_soc": None,
            "max_runtime_h": None,
            "planned_start_time": None,
            "planned_end_time": None,
            "started_at": None,
            "stop_at": None,
            "start_soc": None,
            "last_result": None,
            "service_calls_performed": False,
            "write_count": 0,
            "safe_return_performed": False,
            "safe_return_reason": None,
            "last_finished_at": None,
        }

    @property
    def active(self) -> bool:
        return bool(self._state.get("active"))

    @property
    def busy(self) -> bool:
        return bool(
            self.active
            or self._state.get("status")
            in {"arming_external_mode", "post_mode_stability", "stopping"}
        )

    @property
    def data(self) -> dict[str, Any]:
        result = dict(self._state)
        result["busy"] = self.busy
        result["physical_execution_authority"] = bool(
            self._armed_provider is not None and self._armed_provider()
        )
        result["manual_scheduled_execution_enabled"] = True
        result["automatic_planner_execution_enabled"] = True
        return result

    def _option(self, key: str) -> str | None:
        value = self.entry.options.get(key)
        return str(value) if value else None

    def _control_entities(self) -> tuple[str, str, str]:
        mode = self.entry.options.get("operating_mode_entity")
        direction = self.entry.options.get("action_direction_entity")
        power = self.entry.options.get("power_setpoint_entity")
        if not mode or not direction or not power:
            raise HomeAssistantError("DOEMS control-path is niet volledig geconfigureerd")
        mode = str(mode)
        direction = str(direction)
        power = str(power)
        if not mode.startswith("select.") or not direction.startswith("select."):
            raise HomeAssistantError("DOEMS mode/richting moeten select-entiteiten zijn")
        if not power.startswith("number."):
            raise HomeAssistantError("DOEMS vermogenssetpoint moet een number-entiteit zijn")
        return mode, direction, power

    def _read_soc(self) -> float | None:
        entity_id = self._option(CONF_SOC_ENTITY)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE_SOC_STATES:
            return None
        return parse_soc_percent(state.state)

    def _read_state(self, key: str) -> str | None:
        entity_id = self._option(key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in {"unknown", "unavailable"}:
            return None
        return str(state.state)

    def _read_power(self, key: str) -> float | None:
        entity_id = self._option(key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return normalize_power_w(
            state.state,
            state.attributes.get("unit_of_measurement"),
            allow_negative=False,
        )

    async def _call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        *,
        entity_id: str,
    ) -> None:
        await self.hass.services.async_call(
            domain,
            service,
            data,
            target={"entity_id": entity_id},
            blocking=True,
        )
        self._state["service_calls_performed"] = True
        self._state["write_count"] = int(self._state.get("write_count") or 0) + 1
        await self._async_save()

    async def _async_save(self) -> None:
        await self._store.async_save(dict(self._state))

    async def async_load_and_recover(self) -> None:
        """Recover only an execution that DOEMS itself persisted as active."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            for key in self._state:
                if key in stored:
                    self._state[key] = stored[key]
        interrupted = bool(
            self._state.get("active") is True
            or self._state.get("status")
            in {"arming_external_mode", "post_mode_stability", "running", "stopping"}
        )
        if interrupted:
            self._state["status"] = "restart_recovery"
            self._state["reason"] = "Onderbroken DOEMS-proef wordt fail-safe teruggezet"
            await self._async_save()
            await self.async_stop("restart_recovery", emergency=True)

    async def _wait_for_stable_external_controls(
        self,
        *,
        mode_entity: str,
        direction_entity: str,
        power_entity: str,
        armed_provider: Callable[[], bool],
    ) -> None:
        deadline = dt_util.now() + timedelta(seconds=_CONTROL_WAIT_SECONDS)
        zero_written = False
        while dt_util.now() < deadline:
            if not armed_provider():
                raise HomeAssistantError("DOEMS Automatic Execution werd uitgezet")
            mode = self.hass.states.get(mode_entity)
            direction = self.hass.states.get(direction_entity)
            power = self.hass.states.get(power_entity)
            if (
                mode is not None
                and mode.state == _EXTERNAL_MODE
                and direction is not None
                and direction.state not in {"unknown", "unavailable"}
                and power is not None
                and power.state not in {"unknown", "unavailable"}
            ):
                if not zero_written:
                    await self._call(
                        "number",
                        "set_value",
                        {"value": 0},
                        entity_id=power_entity,
                    )
                    zero_written = True
                    await asyncio.sleep(1)
                    continue
                stable = min(
                    (dt_util.now() - mode.last_changed).total_seconds(),
                    (dt_util.now() - direction.last_changed).total_seconds(),
                    (dt_util.now() - power.last_changed).total_seconds(),
                )
                if stable >= _CONTROL_STABLE_SECONDS:
                    return
            await asyncio.sleep(2)
        raise HomeAssistantError(
            "third_party_control/control-entiteiten werden niet 60 seconden stabiel"
        )

    def _validate_selected_plan(self, snapshot: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """Validate one Scheduler-selected manual or guarded Plan72 action."""
        if snapshot.get("automatic_execution_armed") is not True:
            raise HomeAssistantError("DOEMS Automatic Execution staat uit")
        if snapshot.get("scheduler_ready") is not True:
            raise HomeAssistantError("Scheduler heeft geen startklaar plan")
        slot = snapshot.get("scheduler_selected_slot")
        if not isinstance(slot, int):
            raise HomeAssistantError("Scheduler heeft geen geldig planslot geselecteerd")
        slots = snapshot.get("scheduler_slots") or {}
        detail = slots.get(slot) or slots.get(str(slot)) or {}
        origin = str(detail.get("origin") or "manual")
        if origin not in {"manual", "automatic_72h_planner"}:
            raise HomeAssistantError(f"Onbekende planslot-origin: {origin}")
        if str(detail.get("execution_mode") or "") != "gepland":
            raise HomeAssistantError("Fysieke uitvoering vereist een gepland planslot")
        action = detail.get("action")
        if action not in {"laden", "ontladen"}:
            raise HomeAssistantError("Planslot bevat geen ondersteunde laad/ontlaadactie")
        try:
            power_w = int(float(detail.get("power_w") or 0))
            target_soc = float(detail.get("target_soc") or 0)
            max_runtime_h = float(detail.get("max_runtime_h") or 0)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError("Planslot bevat ongeldige fysieke waarden") from err
        max_power = (
            int(self.settings.max_discharge_power_w)
            if action == "ontladen"
            else int(self.settings.max_charge_power_w)
        )
        if not 100 <= power_w <= max_power:
            raise HomeAssistantError(
                f"Planvermogen valt buiten 100-{max_power} W voor {action}"
            )
        if not 5 <= target_soc <= 100:
            raise HomeAssistantError("Doel-SOC valt buiten 5-100%")
        if not 0.25 <= max_runtime_h <= 12:
            raise HomeAssistantError("Maximale looptijd valt buiten 0,25-12 uur")

        if origin == "automatic_72h_planner":
            planner_identity = detail.get("planner_identity")
            planner_signature = detail.get("planner_signature")
            if not isinstance(planner_identity, str) or not planner_identity:
                raise HomeAssistantError("Automatic Plan72 planner_identity ontbreekt")
            if not isinstance(planner_signature, str) or not planner_signature:
                raise HomeAssistantError("Automatic Plan72 planner_signature ontbreekt")
            if snapshot.get("auto_execution_gate_status") != "armed_ready":
                raise HomeAssistantError("Automatic Execution Gate is niet armed_ready")
            if snapshot.get("auto_execution_gate_execution_permitted") is not True:
                raise HomeAssistantError("Automatic Execution Gate geeft geen uitvoering vrij")
            if snapshot.get("auto_execution_gate_selected_slot") != slot:
                raise HomeAssistantError("Automatic Execution Gate selecteert een ander planslot")
            if snapshot.get("auto_execution_gate_planner_identity") != planner_identity:
                raise HomeAssistantError("Automatic planner_identity is niet stabiel")
            if snapshot.get("auto_execution_gate_action") != action:
                raise HomeAssistantError("Automatic gate-action wijkt af van Scheduler")
            try:
                gate_power = int(float(snapshot.get("auto_execution_gate_power_w") or 0))
                gate_target = float(snapshot.get("auto_execution_gate_target_soc") or 0)
                gate_runtime = float(snapshot.get("auto_execution_gate_max_runtime_h") or 0)
            except (TypeError, ValueError) as err:
                raise HomeAssistantError("Automatic gate bevat ongeldige fysieke waarden") from err
            if gate_power != power_w:
                raise HomeAssistantError("Automatic gate-vermogen wijkt af van planslot")
            if abs(gate_target - target_soc) > 0.001:
                raise HomeAssistantError("Automatic gate-doel-SOC wijkt af van planslot")
            if abs(gate_runtime - max_runtime_h) > 0.0001:
                raise HomeAssistantError("Automatic gate-looptijd wijkt af van planslot")

        return slot, detail

    async def async_start(
        self,
        snapshot: dict[str, Any],
        *,
        refresh: Callable[[str], Any],
        snapshot_provider: Callable[[], dict[str, Any]],
        armed_provider: Callable[[], bool],
    ) -> bool:
        """Physically execute one Scheduler-selected guarded planned action."""
        if self.busy:
            return False

        self._armed_provider = armed_provider
        slot, detail = self._validate_selected_plan(snapshot)

        # Fail before entering third_party_control when the copied manual Safety
        # Guard cannot possibly become complete.
        if self._read_state(CONF_DEVICE_STATUS_ENTITY) is None:
            raise HomeAssistantError("Batterij-apparaatstatus is niet geconfigureerd/beschikbaar")
        if self._read_power(CONF_BATTERY_CHARGE_POWER_ENTITY) is None:
            raise HomeAssistantError("Batterij-laadvermogenbron is niet beschikbaar")
        if self._read_power(CONF_BATTERY_DISCHARGE_POWER_ENTITY) is None:
            raise HomeAssistantError("Batterij-ontlaadvermogenbron is niet beschikbaar")

        action = str(detail["action"])
        origin = str(detail.get("origin") or "manual")
        planner_identity = detail.get("planner_identity")
        planner_signature = detail.get("planner_signature")
        power_w = int(float(detail["power_w"]))
        target_soc = float(detail["target_soc"])
        max_runtime_h = float(detail["max_runtime_h"])
        current_soc = self._read_soc()
        if current_soc is None:
            raise HomeAssistantError("SOC is niet beschikbaar")
        if action == "laden":
            if current_soc >= target_soc:
                raise HomeAssistantError("Laaddoel-SOC is al bereikt")
            opposite = self._read_power(CONF_BATTERY_DISCHARGE_POWER_ENTITY)
            if opposite is not None and opposite > 100:
                raise HomeAssistantError("Batterij ontlaadt; laden wordt niet gestart")
        else:
            if current_soc <= max(5.0, float(self.settings.technical_min_soc_percent)):
                raise HomeAssistantError("Technische minimum-SOC is bereikt")
            if current_soc <= target_soc:
                raise HomeAssistantError("Ontlaaddoel-SOC is al bereikt")
            opposite = self._read_power(CONF_BATTERY_CHARGE_POWER_ENTITY)
            if opposite is not None and opposite > 100:
                raise HomeAssistantError("Batterij laadt; ontladen wordt niet gestart")

        mode_entity, direction_entity, power_entity = self._control_entities()
        start_time = dt_util.now()
        planned_end_raw = detail.get("planned_end_time")
        planned_end = (
            dt_util.parse_datetime(str(planned_end_raw)) if planned_end_raw else None
        )
        if planned_end is not None and planned_end.tzinfo is None:
            planned_end = planned_end.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        stop_at = start_time + timedelta(hours=max_runtime_h)
        if planned_end is not None:
            stop_at = min(stop_at, planned_end)

        self._state.update(
            {
                "active": False,
                "status": "arming_external_mode",
                "reason": f"Plan {slot} wordt fysiek voorbereid",
                "slot": slot,
                "action": action,
                "origin": origin,
                "planner_identity": planner_identity,
                "planner_signature": planner_signature,
                "power_w": power_w,
                "target_soc": target_soc,
                "max_runtime_h": max_runtime_h,
                "planned_start_time": detail.get("start_time"),
                "planned_end_time": detail.get("planned_end_time"),
                "started_at": None,
                "stop_at": stop_at.isoformat(),
                "start_soc": current_soc,
                "last_result": None,
                "safe_return_performed": False,
                "safe_return_reason": None,
            }
        )
        await self._async_save()

        try:
            power_state = self.hass.states.get(power_entity)
            if power_state is not None and power_state.state not in {"unknown", "unavailable"}:
                await self._call(
                    "number", "set_value", {"value": 0}, entity_id=power_entity
                )

            mode_state = self.hass.states.get(mode_entity)
            if mode_state is None or mode_state.state in {"unknown", "unavailable"}:
                raise HomeAssistantError("Operating-mode bron is niet beschikbaar")
            if mode_state.state != _EXTERNAL_MODE:
                await self._call(
                    "select",
                    "select_option",
                    {"option": _EXTERNAL_MODE},
                    entity_id=mode_entity,
                )

            await self._wait_for_stable_external_controls(
                mode_entity=mode_entity,
                direction_entity=direction_entity,
                power_entity=power_entity,
                armed_provider=armed_provider,
            )

            # Re-evaluate the existing safety chain only after the battery has
            # entered third_party_control. Manual actions keep the proven legacy
            # Safety/Action Controller check. Automatic Plan72 actions must pass
            # the existing automatic gate again with the same frozen identity.
            await refresh("physical_post_mode_revalidation")
            live_snapshot = snapshot_provider()
            if not armed_provider():
                raise HomeAssistantError("DOEMS Automatic Execution werd uitgezet")
            if live_snapshot.get("scheduler_ready") is not True:
                raise HomeAssistantError("Scheduler is niet langer startklaar")
            if live_snapshot.get("scheduler_selected_slot") != slot:
                raise HomeAssistantError("Geselecteerd planslot wijzigde tijdens fysieke arming")

            live_plan = self.plan_store.get_plan(slot)
            if str(live_plan.get("lifecycle_status") or "").lower() != "pending":
                raise HomeAssistantError("Planslot is niet langer pending")
            if live_plan.get("action") != action:
                raise HomeAssistantError("Planslotactie wijzigde tijdens fysieke arming")
            if str(live_plan.get("origin") or "manual") != origin:
                raise HomeAssistantError("Planslot-origin wijzigde tijdens fysieke arming")

            if origin == "automatic_72h_planner":
                if live_snapshot.get("auto_execution_gate_status") != "armed_ready":
                    raise HomeAssistantError(
                        f"Automatic gate blokkeert na mode-switch: "
                        f"{live_snapshot.get('auto_execution_gate_status') or 'onbekend'}"
                    )
                if live_snapshot.get("auto_execution_gate_execution_permitted") is not True:
                    raise HomeAssistantError("Automatic gate geeft na mode-switch geen uitvoering vrij")
                if live_snapshot.get("auto_execution_gate_selected_slot") != slot:
                    raise HomeAssistantError("Automatic gate-slot wijzigde tijdens arming")
                if live_snapshot.get("auto_execution_gate_planner_identity") != planner_identity:
                    raise HomeAssistantError("Automatic planner_identity wijzigde tijdens arming")
                if live_snapshot.get("auto_execution_gate_action") != action:
                    raise HomeAssistantError("Automatic gate-action wijzigde tijdens arming")
                try:
                    gate_power = int(float(live_snapshot.get("auto_execution_gate_power_w") or 0))
                    gate_target = float(live_snapshot.get("auto_execution_gate_target_soc") or 0)
                    gate_runtime = float(live_snapshot.get("auto_execution_gate_max_runtime_h") or 0)
                except (TypeError, ValueError) as err:
                    raise HomeAssistantError(
                        "Automatic gate bevat na mode-switch ongeldige fysieke waarden"
                    ) from err
                if gate_power != power_w:
                    raise HomeAssistantError("Automatic gate-vermogen wijzigde tijdens arming")
                if abs(gate_target - target_soc) > 0.001:
                    raise HomeAssistantError("Automatic gate-doel-SOC wijzigde tijdens arming")
                if abs(gate_runtime - max_runtime_h) > 0.0001:
                    raise HomeAssistantError("Automatic gate-looptijd wijzigde tijdens arming")
            else:
                if live_snapshot.get("legacy_safety_safe") is not True:
                    raise HomeAssistantError(
                        f"Safety Guard blokkeert na mode-switch: "
                        f"{live_snapshot.get('legacy_safety_reason') or 'onbekend'}"
                    )
                if live_snapshot.get("controller_ready") is not True:
                    raise HomeAssistantError(
                        f"Action Controller niet gereed na mode-switch: "
                        f"{live_snapshot.get('controller_reason') or 'onbekend'}"
                    )
                if live_snapshot.get("controller_action") != action:
                    raise HomeAssistantError("Action Controller wijzigde richting tijdens arming")

            current_soc = self._read_soc()
            if current_soc is None:
                raise HomeAssistantError("SOC verdween tijdens fysieke arming")
            if action == "laden" and current_soc >= target_soc:
                raise HomeAssistantError("Laaddoel-SOC is tijdens arming al bereikt")
            if action == "ontladen" and current_soc <= target_soc:
                raise HomeAssistantError("Ontlaaddoel-SOC is tijdens arming al bereikt")

            await self._call(
                "select",
                "select_option",
                {"option": "charge" if action == "laden" else "discharge"},
                entity_id=direction_entity,
            )
            await self._call(
                "number",
                "set_value",
                {"value": power_w},
                entity_id=power_entity,
            )

            self._state.update(
                {
                    "active": True,
                    "status": "running",
                    "reason": (
                        f"Plan {slot} actief: {action} {power_w} W tot "
                        f"{target_soc:.0f}% of einde/max looptijd"
                    ),
                    "started_at": dt_util.now().isoformat(),
                }
            )
            await self._async_save()
            lifecycle_reason = (
                "beta2_automatic_plan72_physical_execution_running"
                if origin == "automatic_72h_planner"
                else "step15a_physical_execution_running"
            )
            await self.plan_store.async_mark_lifecycle(slot, "actief", lifecycle_reason)
            self._monitor_task = self.hass.async_create_task(
                self._monitor_loop(), "DOEMS guarded physical execution"
            )
            return True
        except Exception as err:
            _LOGGER.exception("DOEMS Step15A physical start failed")
            await self.async_stop(f"start_failed: {err}", emergency=True)
            raise

    async def _monitor_loop(self) -> None:
        try:
            while self.active:
                await asyncio.sleep(_MONITOR_INTERVAL_SECONDS)
                if not self.active:
                    return
                if self._armed_provider is None or not self._armed_provider():
                    await self.async_stop("automatic_execution_disarmed", emergency=False)
                    return
                action = str(self._state.get("action") or "")
                target = float(self._state.get("target_soc") or 0)
                soc = self._read_soc()
                if soc is None:
                    await self.async_stop("soc_unavailable", emergency=True)
                    return

                mode_entity, direction_entity, power_entity = self._control_entities()
                mode = self.hass.states.get(mode_entity)
                direction = self.hass.states.get(direction_entity)
                setpoint = self.hass.states.get(power_entity)
                expected_direction = "charge" if action == "laden" else "discharge"
                if mode is None or mode.state != _EXTERNAL_MODE:
                    await self.async_stop("operating_mode_changed", emergency=True)
                    return
                if direction is None or direction.state != expected_direction:
                    await self.async_stop("direction_changed", emergency=True)
                    return
                try:
                    setpoint_w = float(setpoint.state) if setpoint is not None else None
                except (TypeError, ValueError):
                    setpoint_w = None
                requested = float(self._state.get("power_w") or 0)
                if setpoint_w is None or abs(setpoint_w - requested) > _POWER_TOLERANCE_W:
                    await self.async_stop("power_setpoint_changed", emergency=True)
                    return

                if action == "laden":
                    opposite = self._read_power(CONF_BATTERY_DISCHARGE_POWER_ENTITY)
                    if opposite is not None and opposite > 100:
                        await self.async_stop("unexpected_discharge", emergency=True)
                        return
                    if soc >= target:
                        await self.async_stop("target_soc_reached", emergency=False)
                        return
                else:
                    opposite = self._read_power(CONF_BATTERY_CHARGE_POWER_ENTITY)
                    if opposite is not None and opposite > 100:
                        await self.async_stop("unexpected_charge", emergency=True)
                        return
                    floor = max(5.0, float(self.settings.technical_min_soc_percent))
                    if soc <= floor:
                        await self.async_stop("minimum_soc_reached", emergency=False)
                        return
                    if soc <= target:
                        await self.async_stop("target_soc_reached", emergency=False)
                        return

                stop_at_raw = self._state.get("stop_at")
                stop_at = dt_util.parse_datetime(str(stop_at_raw)) if stop_at_raw else None
                if stop_at is not None and stop_at.tzinfo is None:
                    stop_at = stop_at.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                if stop_at is not None and dt_util.now() >= stop_at:
                    await self.async_stop("planned_window_or_runtime_ended", emergency=False)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.exception("DOEMS Step15A monitor failed")
            await self.async_stop(f"monitor_failed: {err}", emergency=True)

    async def async_stop(self, reason: str, *, emergency: bool = False) -> None:
        """Always attempt 0 W -> short settle -> self_consumption."""
        slot = self._state.get("slot")
        was_active = bool(self._state.get("active"))
        self._state["active"] = False
        self._state["status"] = "stopping"
        self._state["reason"] = reason
        self._state["safe_return_reason"] = reason
        await self._async_save()

        errors: list[str] = []
        try:
            mode_entity, _direction_entity, power_entity = self._control_entities()
            power = self.hass.states.get(power_entity)
            if power is not None and power.state not in {"unknown", "unavailable"}:
                try:
                    await self._call(
                        "number", "set_value", {"value": 0}, entity_id=power_entity
                    )
                except Exception as err:
                    errors.append(f"zero_power_failed:{err}")
            await asyncio.sleep(1)
            try:
                await self._call(
                    "select",
                    "select_option",
                    {"option": _SELF_MODE},
                    entity_id=mode_entity,
                )
            except Exception as err:
                errors.append(f"self_consumption_failed:{err}")
        except Exception as err:
            errors.append(f"control_path_failed:{err}")

        result = "emergency_stopped" if emergency or errors else "completed"
        if errors:
            reason = f"{reason}; {'; '.join(errors)}"
        self._state.update(
            {
                "status": result,
                "reason": reason,
                "last_result": result,
                "safe_return_performed": not errors,
                "last_finished_at": dt_util.now().isoformat(),
            }
        )
        await self._async_save()

        if was_active and isinstance(slot, int):
            lifecycle = "fout" if result == "emergency_stopped" else "voltooid"
            await self.plan_store.async_mark_lifecycle(slot, lifecycle, reason)

        current = asyncio.current_task()
        if self._monitor_task is not None and self._monitor_task is not current:
            self._monitor_task.cancel()
        self._monitor_task = None

    async def async_shutdown_stop(self) -> None:
        if self.busy:
            await self.async_stop("home_assistant_stop", emergency=True)
