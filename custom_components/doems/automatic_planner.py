"""Cached background runtime for the DOEMS R5 automatic planner shadow."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from functools import partial
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .automatic_planner_runtime import (
    RUNTIME_VERSION,
    compute_automatic_planner_snapshot,
    planner_cycle_id,
    planner_request_signature,
)
from .battery_contract import DOEMSBatteryInputContract
from .const import (
    CONF_MAX_CHARGE_POWER_W,
    CONF_MAX_DISCHARGE_POWER_W,
    CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
    CONF_PEAK_SALE_THRESHOLD_EUR_PER_KWH,
    CONF_SOFTWARE_RESERVE_PERCENT,
    DEFAULT_MAX_CHARGE_POWER_W,
    DEFAULT_MAX_DISCHARGE_POWER_W,
    DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
    DEFAULT_PEAK_SALE_THRESHOLD_EUR_PER_KWH,
    DEFAULT_SOFTWARE_RESERVE_PERCENT,
)
from .energy_coordinator import DOEMSEnergyCoordinator
from .manual_plan_model import PLAN_SLOT_COUNT
from .manual_plan_store import DOEMSManualPlanStore
from .prices import DOEMSPricesManager
from .solar_forecast import SolarForecastManager

_LOGGER = logging.getLogger(__name__)


class DOEMSAutomaticPlanner:
    """Run R5 policy outside the HA event loop and publish one cached snapshot."""

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        entry: ConfigEntry,
        energy: DOEMSEnergyCoordinator | None,
        solar: SolarForecastManager | None,
        prices: DOEMSPricesManager | None,
        battery: DOEMSBatteryInputContract | None,
        plans: DOEMSManualPlanStore,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.energy = energy
        self.solar = solar
        self.prices = prices
        self.battery = battery
        self.plans = plans
        self._listeners: list[Callable[[], None]] = []
        self._source_unsubs: list[Callable[[], None]] = []
        self._cached_snapshot: dict[str, Any] = self._blocked("planner_startup_pending")
        self._generation = 0
        self._published_generation = 0
        self._compute_count = 0
        self._stale_discard_count = 0
        self._same_signature_skip_count = 0
        self._last_request_signature: str | None = None
        self._last_input_signature: str | None = None
        self._last_cycle_id: str | None = None
        self._last_reason: str | None = None
        self._last_refreshed_at: str | None = None
        self._last_error: str | None = None
        self._active_signature: str | None = None
        self._pending_request: dict[str, Any] | None = None
        self._planner_task: asyncio.Task[None] | None = None
        self._shutdown = False
        self._last_battery_ready: bool | None = None
        self._last_capacity_kwh: float | None = None

    async def async_setup(self) -> None:
        if self.energy is not None:
            self._source_unsubs.append(self.energy.async_add_listener(
                partial(self._source_changed, "energy_quarter_or_profile")
            ))
        if self.solar is not None:
            self._source_unsubs.append(self.solar.async_add_listener(
                partial(self._source_changed, "solar_forecast_changed")
            ))
        if self.prices is not None:
            self._source_unsubs.append(self.prices.async_add_listener(
                partial(self._source_changed, "prices_forecast_changed")
            ))
        if self.battery is not None:
            self._remember_battery_state()
            self._source_unsubs.append(
                self.battery.async_add_listener(self._battery_source_changed)
            )
        self._source_unsubs.append(
            self.plans.add_listener(partial(self._source_changed, "manual_plan_changed"))
        )
        await self.async_request_refresh("startup")

    async def async_shutdown(self) -> None:
        self._shutdown = True
        self._pending_request = None
        for unsub in self._source_unsubs:
            unsub()
        self._source_unsubs.clear()
        task = self._planner_task
        self._planner_task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._listeners.clear()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    @callback
    def _source_changed(self, reason: str) -> None:
        if not self._shutdown:
            self.hass.async_create_task(self.async_request_refresh(reason))

    def _remember_battery_state(self) -> tuple[bool, float | None]:
        if self.battery is None:
            self._last_battery_ready = False
            self._last_capacity_kwh = None
            return False, None
        data = self.battery.snapshot()
        ready = bool(
            data.get("status") == "ready"
            and data.get("ready_for_soc_projection") is True
        )
        try:
            capacity = float(data["capacity_kwh"]) if data.get("capacity_kwh") is not None else None
        except (TypeError, ValueError):
            capacity = None
        self._last_battery_ready = ready
        self._last_capacity_kwh = capacity
        return ready, capacity

    @callback
    def _battery_source_changed(self) -> None:
        """Do not recompute for ordinary SOC/power ticks."""
        old_ready = self._last_battery_ready
        old_capacity = self._last_capacity_kwh
        ready, capacity = self._remember_battery_state()
        reason = None
        if old_ready is not None and ready != old_ready:
            reason = "battery_recovered" if ready else "battery_became_unready"
        elif (
            ready
            and old_capacity is not None
            and capacity is not None
            and abs(capacity - old_capacity) > 1e-9
        ):
            reason = "battery_capacity_changed"
        if reason and not self._shutdown:
            self.hass.async_create_task(self.async_request_refresh(reason))

    def _settings(self) -> dict[str, float]:
        o = self.entry.options
        return {
            "software_reserve_percent": float(o.get(
                CONF_SOFTWARE_RESERVE_PERCENT, DEFAULT_SOFTWARE_RESERVE_PERCENT
            )),
            "max_charge_power_w": float(o.get(
                CONF_MAX_CHARGE_POWER_W, DEFAULT_MAX_CHARGE_POWER_W
            )),
            "max_discharge_power_w": float(o.get(
                CONF_MAX_DISCHARGE_POWER_W, DEFAULT_MAX_DISCHARGE_POWER_W
            )),
            "minimum_trade_margin_eur_per_kwh": float(o.get(
                CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
                DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
            )),
            "peak_sale_threshold_eur_per_kwh": float(o.get(
                CONF_PEAK_SALE_THRESHOLD_EUR_PER_KWH,
                DEFAULT_PEAK_SALE_THRESHOLD_EUR_PER_KWH,
            )),
        }

    def _blocked(self, *blockers: str) -> dict[str, Any]:
        return {
            "status": "blocked",
            "valid": False,
            "blockers": list(blockers),
            "native_slots": [],
            "hourly_plan": [],
            "candidates": [],
            "timeline_points": [],
            "candidate_count": 0,
            "native_slot_count": 0,
            "clock_hour_bucket_count": 0,
            "automatic_planner_active": True,
            "automatic_plan_store_writes": False,
            "scheduler_active": False,
            "safety_prestart_active": False,
            "execution_enabled": False,
            "physical_execution_authority": False,
            "mode": "automatic_planner_shadow",
            "observational_only": True,
            "runtime_version": RUNTIME_VERSION,
        }

    def _runtime_metadata(self) -> dict[str, Any]:
        return {
            "planner_refresh_policy": "native_quarter_plus_events",
            "planner_generation": self._generation,
            "planner_published_generation": self._published_generation,
            "planner_compute_count": self._compute_count,
            "planner_stale_discard_count": self._stale_discard_count,
            "planner_same_signature_skip_count": self._same_signature_skip_count,
            "planner_last_request_signature": self._last_request_signature,
            "planner_last_input_signature": self._last_input_signature,
            "planner_last_cycle_id": self._last_cycle_id,
            "planner_last_refresh_reason": self._last_reason,
            "planner_last_refreshed_at": self._last_refreshed_at,
            "planner_worker_active": bool(
                self._planner_task is not None and not self._planner_task.done()
            ),
            "planner_last_error": self._last_error,
        }

    def _freeze_request(
        self, reason: str
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if self.energy is None:
            return None, ["energy_forecast_unavailable"]
        if self.solar is None:
            return None, ["solar_forecast_unavailable"]
        if self.prices is None:
            return None, ["prices_forecast_unavailable"]
        if self.battery is None:
            return None, ["battery_input_contract_unavailable"]

        battery = self.battery.snapshot()
        if battery.get("status") != "ready" or battery.get("ready_for_soc_projection") is not True:
            return None, [
                "battery_input_not_ready",
                *[str(value) for value in battery.get("blockers", [])],
            ]
        soc = battery.get("soc_percent")
        capacity = battery.get("capacity_kwh")
        if soc is None or capacity is None:
            return None, ["battery_soc_or_capacity_missing"]

        reference = dt_util.as_utc(dt_util.utcnow())
        energy_records = list(self.energy.records)
        solar_slots = [
            {"start": point.start.isoformat(), "solar_kwh": point.total_kwh}
            for point in self.solar.points
        ]
        plans = [
            {**self.plans.get_plan(slot), "slot": slot}
            for slot in range(1, PLAN_SLOT_COUNT + 1)
        ]
        price_rows = [
            dict(item)
            for item in self.prices.timeline_slots
            if isinstance(item, dict) and item.get("time")
        ]
        price_by_start = {str(item["time"]): item for item in price_rows}
        settings = self._settings()

        first_energy = energy_records[0] if energy_records else {}
        last_energy = energy_records[-1] if energy_records else {}
        source_markers = {
            "energy": {
                "profile": self.energy.profile,
                "count": len(energy_records),
                "first_start": first_energy.get("start"),
                "last_start": last_energy.get("start"),
                "last_energy_kwh": last_energy.get("energy_kwh"),
                "last_valid": last_energy.get("valid"),
            },
            "solar": {
                "last_successful_update": (
                    self.solar.last_successful_update.isoformat()
                    if self.solar.last_successful_update else None
                ),
                "count": len(solar_slots),
                "first": solar_slots[0] if solar_slots else {},
                "last": solar_slots[-1] if solar_slots else {},
            },
            "prices": {
                "last_update": self.prices.last_update.isoformat()
                if self.prices.last_update else None,
                "source_generated_at": self.prices.source_generated_at,
                "forecast_generated_at": self.prices.forecast_generated_at,
                "count": len(price_rows),
                "first": price_rows[0] if price_rows else {},
                "last": price_rows[-1] if price_rows else {},
            },
        }
        signature = planner_request_signature(
            reference=reference,
            source_markers=source_markers,
            plans=plans,
            start_soc_percent=float(soc),
            capacity_kwh=float(capacity),
            settings=settings,
        )
        return {
            "reason": reason,
            "reference": reference,
            "cycle_id": planner_cycle_id(reference),
            "request_signature": signature,
            "compute_kwargs": {
                "reference": reference,
                "energy_records": energy_records,
                "energy_profile": self.energy.profile,
                "local_timezone": dt_util.DEFAULT_TIME_ZONE,
                "solar_slots": solar_slots,
                "plans": plans,
                "start_soc_percent": float(soc),
                "capacity_kwh": float(capacity),
                "price_by_start": price_by_start,
                "settings": settings,
            },
        }, []

    def _publish_blocked(self, blockers: list[str], reason: str) -> None:
        self._generation += 1
        self._pending_request = None
        self._last_reason = reason
        snapshot = self._blocked(*blockers)
        snapshot.update(self._runtime_metadata())
        self._cached_snapshot = snapshot
        self._notify()

    async def async_request_refresh(self, reason: str) -> bool:
        """Queue only the newest unique generation."""
        if self._shutdown:
            return False
        request, blockers = self._freeze_request(reason)
        if request is None:
            self._publish_blocked(blockers, reason)
            return False

        signature = str(request["request_signature"])
        pending_signature = (
            str(self._pending_request.get("request_signature"))
            if self._pending_request is not None else None
        )
        if (
            (self._planner_task is None and signature == self._last_request_signature)
            or signature == self._active_signature
            or signature == pending_signature
        ):
            self._same_signature_skip_count += 1
            return False

        self._generation += 1
        request["generation"] = self._generation
        self._pending_request = request
        if self._planner_task is None or self._planner_task.done():
            self._planner_task = self.hass.async_create_task(
                self._async_planner_loop(),
                "DOEMS R5.1 automatic planner",
            )
        return True

    async def _async_planner_loop(self) -> None:
        try:
            while self._pending_request is not None and not self._shutdown:
                request = self._pending_request
                self._pending_request = None
                await self._async_compute(request)
        finally:
            self._active_signature = None
            self._planner_task = None
            if self._pending_request is not None and not self._shutdown:
                self._planner_task = self.hass.async_create_task(
                    self._async_planner_loop(),
                    "DOEMS R5.1 automatic planner",
                )

    async def _async_compute(self, request: dict[str, Any]) -> None:
        generation = int(request["generation"])
        signature = str(request["request_signature"])
        self._active_signature = signature
        self._compute_count += 1
        try:
            worker = partial(
                compute_automatic_planner_snapshot,
                **request["compute_kwargs"],
            )
            snapshot = await self.hass.async_add_executor_job(worker)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            if generation == self._generation:
                self._last_error = f"{type(err).__name__}: {err}"
                self._last_reason = str(request["reason"])
                failed = self._blocked("planner_compute_failed")
                failed.update(self._runtime_metadata())
                self._cached_snapshot = failed
                self._notify()
            _LOGGER.exception("DOEMS R5.1 automatic planner generation failed")
            return
        finally:
            if self._active_signature == signature:
                self._active_signature = None

        if generation != self._generation:
            self._stale_discard_count += 1
            return

        self._published_generation = generation
        self._last_request_signature = signature
        self._last_input_signature = str(snapshot.get("planner_input_signature") or "") or None
        self._last_cycle_id = str(request["cycle_id"])
        self._last_reason = str(request["reason"])
        self._last_refreshed_at = dt_util.utcnow().isoformat()
        self._last_error = None
        snapshot.update(self._runtime_metadata())
        snapshot["planner_worker_active"] = False
        self._cached_snapshot = snapshot
        self._notify()

    def snapshot(self) -> dict[str, Any]:
        """Return the cache only; sensor reads never execute planner policy."""
        return self._cached_snapshot
