"""Read-only Plan72 runtime and registered Home Assistant entities.

All Home Assistant reads happen on the event loop. One worker evaluates a
private, frozen input snapshot; superseded results can never become current.
This module has no service calls, plan-slot writes or execution authority.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from math import isfinite, sqrt
from typing import Any, Callable

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENERGY_NEED_CAPACITY_ENTITY,
    CONF_ENERGY_NEED_MIN_SOC_ENTITY,
    CONF_ENERGY_NEED_RESERVE_PERCENT,
    CONF_ENERGY_NEED_ROUNDTRIP_EFFICIENCY,
    CONF_ENERGY_NEED_SOC_ENTITY,
    CONF_INSTANCE_NAME,
    CONF_PLAN72_MAX_CHARGE_POWER_W,
    CONF_PLAN72_MAX_DISCHARGE_POWER_W,
    CONF_PLAN72_MINIMUM_TRADE_MARGIN,
    CONF_PLAN72_TRADE_ENABLED,
    DEFAULT_INSTANCE_NAME,
    DEVICE_IDENTIFIER,
    DOMAIN,
    FORECAST_SLOTS,
    NAME,
    VERSION,
)
from .energy_forecast import ceil_quarter
from .energy_need import calculate_energy_need
from .planner_72h import calculate_plan72

_LOGGER = logging.getLogger(__name__)


def _unavailable(reason: str, *, status: str = "invalid") -> dict[str, Any]:
    """Never expose an old executable-looking timeline while inputs are invalid."""
    return {
        "status": status,
        "valid": False,
        "reason": reason,
        "observational_only": True,
        "execution_enabled": False,
        "physical_execution_authority": False,
        "timeline": [],
        "slot_count": 0,
        "totals": {},
        "trade": {},
        "manual": {},
    }


@dataclass(frozen=True, slots=True)
class Plan72Inputs:
    """Only immutable primitive values cross the event-loop/worker boundary."""

    now: datetime
    home: tuple[tuple[datetime, Any], ...]
    solar: tuple[tuple[datetime, Any], ...]
    prices: tuple[tuple[datetime, Any, Any, str, Any], ...]
    parameters: tuple[tuple[str, Any], ...]
    source_metadata: tuple[tuple[str, Any], ...]
    fingerprint: str
    replan_reason: str


def _evaluate(inputs: Plan72Inputs) -> dict[str, Any]:
    """Pure worker entry point; intentionally receives no HA objects."""
    home = [{"start": start, "energy_kwh": value} for start, value in inputs.home]
    solar = [{"start": start, "energy_kwh": value} for start, value in inputs.solar]
    prices = [
        {
            "start": start,
            "import_all_in": import_price,
            "export_all_in": export_price,
            "kind": kind,
            "source_resolution_minutes": resolution,
        }
        for start, import_price, export_price, kind, resolution in inputs.prices
    ]
    parameters = dict(inputs.parameters)
    need = calculate_energy_need(
        home,
        solar,
        now=inputs.now,
        **{
            key: parameters[key]
            for key in (
                "soc_percent",
                "capacity_kwh",
                "min_soc_percent",
                "reserve_percent",
                "charge_efficiency",
                "discharge_efficiency",
            )
        },
    )
    if not need.get("valid"):
        result = _unavailable("energy_need_" + str(need.get("reason", "invalid")))
    else:
        result = calculate_plan72(
            home,
            solar,
            prices,
            now=inputs.now,
            manual_plans=(),
            **parameters,
        )
    # Retain the price provider's native resolution alongside its source kind.
    # Match by time even for metadata; a repeated hourly tariff is not a native
    # quarter-price observation.
    resolutions = {start: resolution for start, _, _, _, resolution in inputs.prices}
    for row in result.get("timeline", []):
        timestamp = datetime.fromisoformat(row["start"].replace("Z", "+00:00"))
        row["source_resolution_minutes"] = resolutions.get(timestamp)
    # The old chapter-4 entities remain untouched. This is its unchanged pure
    # calculation evaluated against exactly the input used by this plan.
    result["energy_need"] = need
    return result


class Plan72Runtime:
    """Coalesce events and publish only the latest complete input generation."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: Any,
        solar: Any,
        prices: Any,
        energy_need: Any,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.solar = solar
        self.prices = prices
        self.energy_need = energy_need
        self.snapshot = _unavailable("initializing")
        self.listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._worker_task: asyncio.Task | None = None
        self._pending: tuple[int, Plan72Inputs] | None = None
        self._revision = 0
        self._requested_fingerprint: str | None = None
        self._closed = False
        self.calculation_count = 0
        self.device = DeviceInfo(
            identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
            name=entry.options.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
            manufacturer=NAME,
            model="Energy Management System",
            sw_version=VERSION,
        )

    async def async_setup(self) -> None:
        for source, reason in (
            (self.coordinator, "home_forecast_changed"),
            (self.solar, "solar_forecast_changed"),
            (self.prices, "prices_changed"),
            (self.energy_need, "energy_need_changed"),
        ):
            if source is not None:
                self._unsubs.append(
                    source.async_add_listener(lambda reason=reason: self.refresh(reason))
                )
        entities = [
            self.entry.options.get(key)
            for key in (
                CONF_ENERGY_NEED_SOC_ENTITY,
                CONF_ENERGY_NEED_CAPACITY_ENTITY,
                CONF_ENERGY_NEED_MIN_SOC_ENTITY,
            )
        ]
        entities = [entity for entity in entities if isinstance(entity, str) and entity]
        if entities:
            self._unsubs.append(
                async_track_state_change_event(self.hass, entities, self._battery_changed)
            )
        self._unsubs.append(
            async_track_time_change(
                self.hass, self._quarter_changed, minute=[0, 15, 30, 45], second=3
            )
        )
        self.refresh("startup")

    async def async_shutdown(self) -> None:
        self._closed = True
        self._revision += 1
        self._pending = None
        for unsubscribe in self._unsubs:
            unsubscribe()
        self._unsubs.clear()
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        # A cancelled executor job may finish its pure arithmetic, but the
        # closed runtime can neither publish it nor queue another worker.
        self.listeners.clear()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self.listeners.append(listener)

        @callback
        def remove_listener() -> None:
            if listener in self.listeners:
                self.listeners.remove(listener)

        return remove_listener

    @callback
    def _notify(self) -> None:
        for listener in tuple(self.listeners):
            listener()

    @callback
    def _battery_changed(self, _event: Any) -> None:
        self.refresh("battery_changed")

    @callback
    def _quarter_changed(self, _now: datetime) -> None:
        self.refresh("quarter_changed")

    def _capture(self, reason: str) -> Plan72Inputs:
        """Read all managers and HA states once, before submitting any job."""
        for name, dependency in (
            ("energy_forecast", self.coordinator),
            ("solar_forecast", self.solar),
            ("prices", self.prices),
            ("energy_need", self.energy_need),
        ):
            if dependency is None:
                raise ValueError("missing_dependency_" + name)
        now = dt_util.utcnow()
        start = ceil_quarter(now)
        solar_status = self.solar.source_status
        price_status = self.prices.status
        price_freshness = self.prices.freshness
        if solar_status != "ok":
            raise ValueError("solar_source_" + str(solar_status))
        if price_status != "ok":
            raise ValueError("prices_source_" + str(price_status))
        if price_freshness != "fresh":
            raise ValueError("prices_source_" + str(price_freshness))
        options = dict(self.entry.options)
        battery: dict[str, Any] = {}
        soc_observed_at = None
        for key, parameter, unit in (
            (CONF_ENERGY_NEED_SOC_ENTITY, "soc_percent", "%"),
            (CONF_ENERGY_NEED_CAPACITY_ENTITY, "capacity_kwh", "kWh"),
            (CONF_ENERGY_NEED_MIN_SOC_ENTITY, "min_soc_percent", "%"),
        ):
            entity_id = options.get(key)
            if not isinstance(entity_id, str) or not entity_id:
                raise ValueError("battery_source_not_configured_" + parameter)
            state = self.hass.states.get(entity_id)
            if state is None or state.state in {"unknown", "unavailable"}:
                raise ValueError("battery_source_unavailable_" + parameter)
            if state.attributes.get("unit_of_measurement") != unit:
                raise ValueError("battery_source_unit_invalid_" + parameter)
            battery[parameter] = state.state
            if parameter == "soc_percent":
                observed = getattr(state, "last_updated", None)
                if isinstance(observed, datetime) and observed.tzinfo is not None and observed.utcoffset() is not None:
                    soc_observed_at = observed.astimezone(timezone.utc).isoformat()
        roundtrip = options.get(CONF_ENERGY_NEED_ROUNDTRIP_EFFICIENCY)
        try:
            efficiency_value = float(roundtrip)
            if isinstance(roundtrip, bool) or not isfinite(efficiency_value) or not 0 < efficiency_value <= 100:
                raise ValueError
            efficiency = sqrt(efficiency_value / 100.0)
        except (ValueError, TypeError):
            raise ValueError("invalid_roundtrip_efficiency") from None
        for option in (CONF_PLAN72_MAX_CHARGE_POWER_W, CONF_PLAN72_MAX_DISCHARGE_POWER_W):
            if option not in options:
                raise ValueError("plan72_power_limits_not_configured")
        parameters = {
            **battery,
            "reserve_percent": options.get(CONF_ENERGY_NEED_RESERVE_PERCENT),
            "charge_efficiency": efficiency,
            "discharge_efficiency": efficiency,
            "max_charge_power_w": options[CONF_PLAN72_MAX_CHARGE_POWER_W],
            "max_discharge_power_w": options[CONF_PLAN72_MAX_DISCHARGE_POWER_W],
            "minimum_trade_margin": options.get(CONF_PLAN72_MINIMUM_TRADE_MARGIN, 0.10),
            "trade_enabled": options.get(CONF_PLAN72_TRADE_ENABLED, True),
        }
        home = tuple((slot.start, slot.energy_kwh) for slot in self.coordinator.forecast(now=now))
        solar_points, missing_solar = self.solar.forecast_window(start=start, slot_count=FORECAST_SLOTS)
        price_points, missing_prices = self.prices.forecast_window(start=start, slot_count=FORECAST_SLOTS)
        if missing_solar:
            raise ValueError("missing_solar_quarters")
        if missing_prices:
            raise ValueError("missing_price_quarters")
        solar = tuple((slot.start, slot.total_kwh) for slot in solar_points)
        prices = tuple(
            (slot.start, slot.import_all_in, slot.export_all_in, slot.kind, slot.source_resolution_minutes)
            for slot in price_points
        )
        # Time within the same untouched quarter and gas-only events are not
        # planner inputs. New prices, power limits, SOC or UTC window are.
        try:
            encoded = json.dumps(
                (start, home, solar, prices, parameters),
                default=lambda value: value.isoformat(),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        except ValueError:
            raise ValueError("nonfinite_planner_input") from None
        return Plan72Inputs(
            now=now,
            home=home,
            solar=solar,
            prices=prices,
            parameters=tuple(parameters.items()),
            source_metadata=(
                ("solar_status", solar_status),
                ("prices_status", price_status),
                ("prices_freshness", price_freshness),
                ("home_profile", str(getattr(self.coordinator, "profile", "unknown"))),
                ("manual_input", "not_connected_until_plan_store"),
                ("soc_observed_at", soc_observed_at),
                ("horizon_start_assumption", "latest_measured_soc_at_next_complete_quarter"),
                ("unmodelled_start_minutes", round((start - now).total_seconds() / 60.0, 6)),
            ),
            fingerprint=sha256(encoded).hexdigest(),
            replan_reason=reason,
        )

    @callback
    def refresh(self, reason: str = "source_changed") -> None:
        if self._closed:
            return
        try:
            inputs = self._capture(reason)
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            self._revision += 1
            self._pending = None
            self._requested_fingerprint = None
            self.snapshot = _unavailable(str(error) or "invalid_input_snapshot")
            self.snapshot["replan_reason"] = reason
            self._notify()
            return
        except Exception:
            _LOGGER.exception("DOEMS Plan72 input capture failed")
            self._revision += 1
            self._pending = None
            self._requested_fingerprint = None
            self.snapshot = _unavailable("input_capture_failed")
            self.snapshot["replan_reason"] = reason
            self._notify()
            return
        if inputs.fingerprint == self._requested_fingerprint:
            return
        self._revision += 1
        self._requested_fingerprint = inputs.fingerprint
        self._pending = (self._revision, inputs)
        self.snapshot = _unavailable("recalculation_pending", status="calculating")
        self.snapshot["replan_reason"] = reason
        self._notify()
        if self._worker_task is None:
            self._worker_task = self.hass.async_create_task(self._run_worker())

    async def _run_worker(self) -> None:
        try:
            while not self._closed and self._pending is not None:
                revision, inputs = self._pending
                self._pending = None
                try:
                    result = await self.hass.async_add_executor_job(_evaluate, inputs)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _LOGGER.exception("DOEMS Plan72 calculation failed")
                    result = _unavailable("calculation_failed")
                self.calculation_count += 1
                if self._closed or revision != self._revision:
                    continue
                if inputs.fingerprint != self._requested_fingerprint:
                    continue
                if ceil_quarter(dt_util.utcnow()) != ceil_quarter(inputs.now):
                    self.refresh("quarter_changed_during_calculation")
                    continue
                if (
                    self.solar.source_status != "ok"
                    or self.prices.status != "ok"
                    or self.prices.freshness != "fresh"
                ):
                    self.refresh("source_validity_changed_during_calculation")
                    continue
                self.snapshot = {
                    **result,
                    "observational_only": True,
                    "execution_enabled": False,
                    "physical_execution_authority": False,
                    "input_fingerprint": inputs.fingerprint,
                    "input_captured_at": inputs.now.isoformat(),
                    "calculated_at": dt_util.utcnow().isoformat(),
                    "plan_generation": revision,
                    "replan_reason": inputs.replan_reason,
                    "sources": dict(inputs.source_metadata),
                }
                self._notify()
        finally:
            self._worker_task = None


@dataclass(frozen=True, slots=True)
class Plan72Field:
    key: str
    label: str
    path: str
    unit: str | None = None
    meaning: str = ""


PLAN72_FIELDS = (
    Plan72Field("status", "Status", "status"),
    Plan72Field("reason", "Reason", "reason"),
    Plan72Field("hours", "Hours", "horizon_hours", "h"),
    Plan72Field("timeline", "Timeline", "slot_count", meaning="One continuous UTC timeline of quarter-hour energy and SOC projections."),
    Plan72Field("start_soc", "Start SOC", "start_soc", "%"),
    Plan72Field("end_soc", "End SOC", "end_soc", "%"),
    Plan72Field("minimum_soc", "Minimum SOC", "min_soc", "%"),
    Plan72Field("maximum_soc", "Maximum SOC", "max_soc", "%"),
    Plan72Field("reserve_target_soc", "Reserve Target SOC", "reserve_target_soc", "%"),
    Plan72Field("reserve", "Reserve", "execution_reserve_kwh", "kWh", "Battery energy at hardware minimum plus the configured extra reserve; no additional execution buffer is added."),
    Plan72Field("reserve_breaches", "Reserve Breaches", "reserve_breach_count", meaning="Projected reserve breaches; validity never grants permission to control the battery."),
    Plan72Field("remaining_charge_need", "Remaining Charge Need", "remaining_charge_need_kwh", "kWh"),
    Plan72Field("solar_charge", "Solar Charge", "totals.charge_from_solar_kwh", "kWh", "AC solar energy entering the battery before charging losses."),
    Plan72Field("safety_charge", "Safety Charge", "totals.charge_from_grid_safety_kwh", "kWh", "AC grid energy scheduled to protect household demand and reserve."),
    Plan72Field("trade_charge", "Trade Charge", "totals.charge_from_grid_trade_kwh", "kWh", "AC grid energy scheduled for a profitable later battery export."),
    Plan72Field("manual_charge", "Manual Charge", "totals.charge_from_grid_manual_kwh", "kWh", "AC charge energy from supplied manual-plan constraints; the HA plan store is not connected in this chapter."),
    Plan72Field("home_discharge", "Home Discharge", "totals.discharge_to_home_kwh", "kWh", "AC battery energy delivered to the home after discharge losses."),
    Plan72Field("grid_discharge", "Grid Discharge", "totals.discharge_to_grid_kwh", "kWh", "AC battery energy delivered to the grid, excluding direct solar export."),
    Plan72Field("manual_grid_discharge", "Manual Grid Discharge", "totals.discharge_to_grid_manual_kwh", "kWh"),
    Plan72Field("grid_import", "Grid Import", "totals.grid_import_for_home_kwh", "kWh", "Residual AC grid import for the home; battery charging is reported separately."),
    Plan72Field("solar_export", "Solar Export", "totals.solar_export_kwh", "kWh", "Direct solar export remaining after the home and feasible solar charging."),
    Plan72Field("losses", "Losses", "totals.losses_kwh", "kWh"),
    Plan72Field("best_charge_time", "Best Charge Time", "trade.best_charge_time"),
    Plan72Field("best_discharge_time", "Best Discharge Time", "trade.best_discharge_time"),
    Plan72Field("best_charge_price", "Best Charge Price", "trade.best_charge_price", "EUR/kWh"),
    Plan72Field("best_discharge_price", "Best Discharge Price", "trade.best_discharge_price", "EUR/kWh"),
    Plan72Field("effective_charge_cost", "Effective Charge Cost", "trade.effective_charge_cost", "EUR/kWh"),
    Plan72Field("expected_trade_margin", "Expected Trade Margin", "trade.expected_margin", "EUR/kWh"),
    Plan72Field("trade_candidates", "Trade Candidates", "trade.candidate_count"),
    Plan72Field("trade_accepted", "Trade Accepted", "trade.accepted_count"),
    Plan72Field("manual_plans", "Manual Plans", "manual.accepted_count"),
    Plan72Field("replan_reason", "Replan Reason", "replan_reason"),
)


def _value(snapshot: dict[str, Any], path: str) -> Any:
    value: Any = snapshot
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


class _Plan72Entity:
    _attr_should_poll = False
    _attr_has_entity_name = False

    def _setup_runtime(self, runtime: Plan72Runtime, suffix: str, label: str) -> None:
        self.runtime = runtime
        self._remove_listener = None
        self._attr_name = "DOEMS EMS Plan72 " + label
        self._attr_unique_id = "doems_ems_plan72_" + suffix
        self._attr_suggested_object_id = self._attr_unique_id
        self._attr_device_info = runtime.device

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.runtime.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snapshot = self.runtime.snapshot
        return {
            "observational_only": True,
            "physical_execution_authority": False,
            "execution_enabled": False,
            "plan_generation": snapshot.get("plan_generation"),
            "calculated_at": snapshot.get("calculated_at"),
            "input_captured_at": snapshot.get("input_captured_at"),
        }


class Plan72Sensor(_Plan72Entity, SensorEntity):
    _unrecorded_attributes = frozenset({"timeline", "energy_need", "sources", "trade", "manual"})

    def __init__(self, runtime: Plan72Runtime, field: Plan72Field) -> None:
        self.field = field
        self._setup_runtime(runtime, field.key, field.label)
        if field.unit:
            self._attr_native_unit_of_measurement = field.unit
        if field.unit == "kWh":
            self._attr_device_class = SensorDeviceClass.ENERGY
        elif field.unit == "%":
            self._attr_device_class = SensorDeviceClass.BATTERY
        elif field.unit == "h":
            self._attr_device_class = SensorDeviceClass.DURATION
        elif field.key in {"best_charge_time", "best_discharge_time"}:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> Any:
        if not self.runtime.snapshot.get("valid") and self.field.key not in {
            "status", "reason", "replan_reason", "timeline"
        }:
            return None
        value = _value(self.runtime.snapshot, self.field.path)
        if self.field.key in {"best_charge_time", "best_discharge_time"} and value is not None:
            if isinstance(value, datetime):
                return value if value.tzinfo is not None and value.utcoffset() is not None else None
            try:
                value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None
            return value if value.tzinfo is not None and value.utcoffset() is not None else None
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = super().extra_state_attributes
        if self.field.meaning:
            attributes["meaning"] = self.field.meaning
        if self.field.key == "remaining_charge_need":
            attributes["energy_basis"] = self.runtime.snapshot.get("remaining_charge_need_basis")
        if self.field.key == "timeline":
            snapshot = self.runtime.snapshot
            attributes.update({
                "schema_version": 1,
                "resolution_minutes": 15,
                "start": snapshot.get("start"),
                "end": snapshot.get("end"),
                "valid": bool(snapshot.get("valid")),
                "input_fingerprint": snapshot.get("input_fingerprint"),
                "flow_energy_basis": "ac",
                "stored_energy_basis": "battery",
                "timeline": snapshot.get("timeline", []),
                "energy_need": snapshot.get("energy_need", {}),
                "sources": snapshot.get("sources", {}),
                "trade": snapshot.get("trade", {}),
                "manual": snapshot.get("manual", {}),
            })
        return attributes


class Plan72BinarySensor(_Plan72Entity, BinarySensorEntity):
    def __init__(self, runtime: Plan72Runtime, suffix: str, label: str, path: str) -> None:
        self.path = path
        self._setup_runtime(runtime, suffix, label)

    @property
    def is_on(self) -> bool | None:
        if self.path == "valid":
            return bool(self.runtime.snapshot.get("valid"))
        if not self.runtime.snapshot.get("valid"):
            return None
        value = _value(self.runtime.snapshot, self.path)
        return bool(value) if value is not None else None


def build_plan72_sensors(runtime: Plan72Runtime) -> list[Plan72Sensor]:
    return [Plan72Sensor(runtime, field) for field in PLAN72_FIELDS]


def build_plan72_binary_sensors(runtime: Plan72Runtime) -> list[Plan72BinarySensor]:
    return [
        Plan72BinarySensor(runtime, "valid", "Valid", "valid"),
        Plan72BinarySensor(runtime, "reserve_satisfied", "Reserve Satisfied", "reserve_satisfied"),
        Plan72BinarySensor(runtime, "trade_profitable", "Trade Profitable", "trade.profitable"),
    ]
