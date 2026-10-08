"""Cached runtime for the DOEMS Automatic and Combined Planners."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from functools import partial
import logging
import time
from threading import Event
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .battery_contract import DOEMSBatteryInputContract
from .planner_diagnostics import PlannerDiagnostics
from .const import (
    CONF_PLANNER_MAX_CHARGE_POWER_W,
    CONF_PLANNER_MAX_DISCHARGE_POWER_W,
    CONF_PLANNER_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
    CONF_PLANNER_SOFTWARE_RESERVE_PERCENT,
    DEFAULT_PLANNER_MAX_CHARGE_POWER_W,
    DEFAULT_PLANNER_MAX_DISCHARGE_POWER_W,
    DEFAULT_PLANNER_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
    DEFAULT_PLANNER_SOFTWARE_RESERVE_PERCENT,
)
from .energy_coordinator import DOEMSEnergyCoordinator
from .manual_plan_model import PLAN_SLOT_COUNT
from .manual_plan_store import DOEMSManualPlanStore
from .prices import DOEMSPricesManager
from .automatic_combined_planner_model import (
    PlannerComputeBudgetExceeded,
    PlannerComputeCancelled,
)
from .automatic_combined_planner_runtime import (
    RUNTIME_VERSION,
    PLANNER_COMPUTE_BUDGET_SECONDS,
    make_planner_work_guard,
    compute_planner_bundle,
    planner_cycle_id,
    planner_request_signature,
)
from .solar_forecast import SolarForecastManager

_LOGGER = logging.getLogger(__name__)


class DOEMSPlannerManager:
    """Serial Automatic -> Combined planner; manual-only refreshes Combined."""

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
        self._cached_bundle = self._blocked_bundle("planner_startup_pending")
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
        self._active_cancel_event: Event | None = None
        self._active_generation: int | None = None
        self._cancel_count = 0
        self._budget_exceeded_count = 0
        self._last_compute_seconds: float | None = None
        self._auto_revision = 0
        self._manual_revision = 0
        self._active_stage: str | None = None
        self._automatic_context: dict[str, Any] | None = None
        self._automatic_published_generation = 0
        self._automatic_compute_count = 0
        self._combined_compute_count = 0
        self._automatic_last_compute_seconds: float | None = None
        self._combined_last_compute_seconds: float | None = None
        self._automatic_diagnostics: dict[str, Any] | None = None
        self._combined_diagnostics: dict[str, Any] | None = None

    async def async_setup(self) -> None:
        if self.energy is not None:
            self._source_unsubs.append(
                self.energy.async_add_listener(
                    partial(
                        self._source_changed,
                        "energy_quarter_or_profile",
                    )
                )
            )
        if self.solar is not None:
            self._source_unsubs.append(
                self.solar.async_add_listener(
                    partial(
                        self._source_changed,
                        "solar_forecast_changed",
                    )
                )
            )
        if self.prices is not None:
            self._source_unsubs.append(
                self.prices.async_add_listener(
                    partial(
                        self._source_changed,
                        "prices_forecast_changed",
                    )
                )
            )
        if self.battery is not None:
            self._remember_battery_state()
            self._source_unsubs.append(
                self.battery.async_add_listener(
                    self._battery_source_changed
                )
            )
        self._source_unsubs.append(
            self.plans.add_listener(
                partial(self._source_changed, "manual_plan_changed")
            )
        )
        await self.async_request_refresh("startup")

    async def async_shutdown(self) -> None:
        self._shutdown = True
        self._pending_request = None
        if self._active_cancel_event is not None:
            self._active_cancel_event.set()
        for unsub in self._source_unsubs:
            unsub()
        self._source_unsubs.clear()
        task = self._planner_task
        self._planner_task = None
        if task is not None and not task.done():
            try:
                # First let cooperative checkpoints terminate the executor.
                await asyncio.wait_for(task, timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        self._listeners.clear()

    def async_add_listener(
        self, listener: Callable[[], None]
    ) -> Callable[[], None]:
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
        if self._shutdown:
            return
        if reason == "manual_plan_changed":
            # A manual edit may never restart/cancel an active Automatic run.
            self.hass.async_create_task(
                self.async_request_manual_refresh(reason)
            )
        else:
            self.hass.async_create_task(
                self.async_request_refresh(reason)
            )

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
            capacity = (
                float(data["capacity_kwh"])
                if data.get("capacity_kwh") is not None
                else None
            )
        except (TypeError, ValueError):
            capacity = None
        self._last_battery_ready = ready
        self._last_capacity_kwh = capacity
        return ready, capacity

    @callback
    def _battery_source_changed(self) -> None:
        """Do not run the heavy planner for ordinary SOC/power telemetry ticks."""
        old_ready = self._last_battery_ready
        old_capacity = self._last_capacity_kwh
        ready, capacity = self._remember_battery_state()
        reason = None
        if old_ready is not None and ready != old_ready:
            reason = (
                "battery_recovered"
                if ready
                else "battery_became_unready"
            )
        elif (
            ready
            and old_capacity is not None
            and capacity is not None
            and abs(capacity - old_capacity) > 1e-9
        ):
            reason = "battery_capacity_changed"
        if reason and not self._shutdown:
            self.hass.async_create_task(
                self.async_request_refresh(reason)
            )

    def _settings(self) -> dict[str, float]:
        options = self.entry.options
        return {
            "software_reserve_percent": float(
                options.get(
                    CONF_PLANNER_SOFTWARE_RESERVE_PERCENT,
                    DEFAULT_PLANNER_SOFTWARE_RESERVE_PERCENT,
                )
            ),
            "max_charge_power_w": float(
                options.get(
                    CONF_PLANNER_MAX_CHARGE_POWER_W,
                    DEFAULT_PLANNER_MAX_CHARGE_POWER_W,
                )
            ),
            "max_discharge_power_w": float(
                options.get(
                    CONF_PLANNER_MAX_DISCHARGE_POWER_W,
                    DEFAULT_PLANNER_MAX_DISCHARGE_POWER_W,
                )
            ),
            "minimum_trade_margin_eur_per_kwh": float(
                options.get(
                    CONF_PLANNER_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
                    DEFAULT_PLANNER_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
                )
            ),
        }

    def _blocked_snapshot(
        self, *blockers: str, combined: bool
    ) -> dict[str, Any]:
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
            "planner_enabled": True,
            "plan_store_writes_enabled": False,
            "scheduler_enabled": False,
            "safety_prestart_enabled": False,
            "execution_enabled": False,
            "physical_execution_enabled": False,
            "peak_sale_enabled": False,
            "mode": ("combined_planner" if combined else "automatic_planner"),
            "runtime_version": RUNTIME_VERSION,
        }

    def _blocked_bundle(self, *blockers: str) -> dict[str, Any]:
        return {
            "status": "blocked",
            "valid": False,
            "blockers": list(blockers),
            "automatic": self._blocked_snapshot(
                *blockers, combined=False
            ),
            "combined": self._blocked_snapshot(
                *blockers, combined=True
            ),
            "runtime_version": RUNTIME_VERSION,
            "physical_execution_enabled": False,
        }

    def _runtime_metadata(self) -> dict[str, Any]:
        return {
            "planner_refresh_policy": "native_quarter_plus_events",
            "planner_generation": self._generation,
            "planner_published_generation": self._published_generation,
            "planner_compute_count": self._compute_count,
            "planner_stale_discard_count": self._stale_discard_count,
            "planner_same_signature_skip_count": (
                self._same_signature_skip_count
            ),
            "planner_last_request_signature": (
                self._last_request_signature
            ),
            "planner_last_input_signature": self._last_input_signature,
            "planner_last_cycle_id": self._last_cycle_id,
            "planner_last_refresh_reason": self._last_reason,
            "planner_last_refreshed_at": self._last_refreshed_at,
            "planner_worker_active": bool(
                self._planner_task is not None
                and not self._planner_task.done()
            ),
            "planner_last_error": self._last_error,
            "planner_cancel_count": self._cancel_count,
            "planner_budget_exceeded_count": self._budget_exceeded_count,
            "planner_last_compute_seconds": self._last_compute_seconds,
            "planner_compute_budget_seconds": PLANNER_COMPUTE_BUDGET_SECONDS,
            "planner_automatic_diagnostics": self._automatic_diagnostics,
            "planner_combined_diagnostics": self._combined_diagnostics,
            "planner_automatic_compute_count": self._automatic_compute_count,
            "planner_combined_compute_count": self._combined_compute_count,
            "planner_automatic_last_compute_seconds": self._automatic_last_compute_seconds,
            "planner_combined_last_compute_seconds": self._combined_last_compute_seconds,
            "planner_automatic_published_generation": self._automatic_published_generation,
            "planner_manual_revision": self._manual_revision,
            "planner_active_stage": self._active_stage,
            "planner_combined_pending": bool(
                self._pending_request is not None
                and self._pending_request.get("stage") == "combined"
            ),
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
        if (
            battery.get("status") != "ready"
            or battery.get("ready_for_soc_projection") is not True
        ):
            return None, [
                "battery_input_not_ready",
                *[
                    str(value)
                    for value in battery.get("blockers", [])
                ],
            ]
        soc = battery.get("soc_percent")
        capacity = battery.get("capacity_kwh")
        if soc is None or capacity is None:
            return None, ["battery_soc_or_capacity_missing"]

        reference = dt_util.as_utc(dt_util.utcnow())
        energy_records = [
            dict(item) for item in self.energy.records
        ]
        solar_slots = [
            {
                "start": point.start.isoformat(),
                "solar_kwh": point.total_kwh,
            }
            for point in self.solar.points
        ]
        # Automatic remains independent of R2-R4 Plan Store content.
        # The latest three manual slots are captured ONLY for Combined.
        plans: list[dict[str, Any]] = []
        price_rows = [
            dict(item)
            for item in self.prices.planner_timeline_slots(
                reference
            )
            if isinstance(item, dict) and item.get("time")
        ]
        price_by_start = {
            str(item["time"]): item for item in price_rows
        }
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
                    if self.solar.last_successful_update
                    else None
                ),
                "count": len(solar_slots),
                "first": solar_slots[0] if solar_slots else {},
                "last": solar_slots[-1] if solar_slots else {},
            },
            "prices": {
                "last_update": (
                    self.prices.last_update.isoformat()
                    if self.prices.last_update
                    else None
                ),
                "source_generated_at": (
                    self.prices.source_generated_at
                ),
                "forecast_generated_at": (
                    self.prices.forecast_generated_at
                ),
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

    def _manual_plans_snapshot(self) -> list[dict[str, Any]]:
        """R2-R4 is read-only; only Combined receives these three plans."""
        return [
            {**self.plans.get_plan(slot), "slot": slot}
            for slot in range(1, PLAN_SLOT_COUNT + 1)
        ]

    def _ensure_worker(self) -> None:
        if not self._shutdown and (
            self._planner_task is None or self._planner_task.done()
        ):
            self._planner_task = self.hass.async_create_task(
                self._async_planner_loop(),
                "DOEMS sequential Automatic then Combined planner",
            )

    def _publish_blocked(
        self, blockers: list[str], reason: str
    ) -> None:
        self._generation += 1
        self._auto_revision += 1
        self._automatic_context = None
        self._pending_request = None
        if self._active_cancel_event is not None:
            self._active_cancel_event.set()
        self._last_reason = reason
        bundle = self._blocked_bundle(*blockers)
        metadata = self._runtime_metadata()
        metadata["planner_worker_active"] = False
        bundle.update(metadata)
        for key in ("automatic", "combined"):
            bundle[key].update(metadata)
        self._cached_bundle = bundle
        self._notify()

    async def async_request_refresh(self, reason: str) -> bool:
        """New quarter or changed forecast: Automatic, then Combined."""
        if self._shutdown:
            return False
        request, blockers = self._freeze_request(reason)
        if request is None:
            self._publish_blocked(blockers, reason)
            return False
        signature = str(request["request_signature"])
        if (
            self._pending_request is not None
            and self._pending_request.get("stage") == "automatic"
            and self._pending_request.get("request_signature") == signature
        ) or (
            self._active_stage == "automatic"
            and signature == self._active_signature
        ):
            self._same_signature_skip_count += 1
            return False
        if (
            self._automatic_context is not None
            and signature == self._last_request_signature
        ):
            if (
                self._cached_bundle.get("combined", {}).get("status") != "ready"
                and self._active_stage is None
                and self._pending_request is None
            ):
                self._generation += 1
                self._enqueue_combined(reason)
            else:
                self._same_signature_skip_count += 1
            return False

        self._generation += 1
        self._auto_revision += 1
        self._automatic_context = None
        if self._active_cancel_event is not None:
            self._active_cancel_event.set()
        request.update({
            "stage": "automatic",
            "generation": self._generation,
            "auto_revision": self._auto_revision,
            "manual_revision": self._manual_revision,
        })
        self._pending_request = request
        self._ensure_worker()
        return True

    async def async_request_manual_refresh(
        self, reason: str = "manual_plan_changed"
    ) -> bool:
        """Manual changes only invalidate Combined, not running Automatic."""
        if self._shutdown:
            return False
        self._generation += 1
        self._manual_revision += 1
        if (
            self._active_stage == "automatic"
            or (
                self._pending_request is not None
                and self._pending_request.get("stage") == "automatic"
            )
        ):
            return True
        if self._automatic_context is None:
            # No completed Automatic base exists: recover in correct order.
            return await self.async_request_refresh("missing_automatic_base")
        if self._active_stage == "combined" and self._active_cancel_event:
            self._active_cancel_event.set()
        self._enqueue_combined(reason)
        return True

    def _enqueue_combined(self, reason: str) -> bool:
        context = self._automatic_context
        if context is None or self._shutdown:
            return False
        if (
            self._pending_request is not None
            and self._pending_request.get("stage") == "automatic"
        ):
            return False
        frozen = dict(context["compute_kwargs"])
        frozen.update({
            "plans": self._manual_plans_snapshot(),
            "stage": "combined",
            "automatic_snapshot": context["automatic"],
            "prebuilt_energy_slots": context["energy_slots"],
        })
        self._pending_request = {
            "stage": "combined",
            "reason": reason,
            "generation": self._generation,
            "auto_revision": context["auto_revision"],
            "manual_revision": self._manual_revision,
            "cycle_id": context["cycle_id"],
            "request_signature": context["signature"],
            "compute_kwargs": frozen,
        }
        self._ensure_worker()
        return True

    async def _async_planner_loop(self) -> None:
        """One serial worker: no concurrent Automatic/Combined computation."""
        try:
            while self._pending_request is not None and not self._shutdown:
                request = self._pending_request
                self._pending_request = None
                await self._async_compute(request)
        finally:
            self._active_signature = None
            self._planner_task = None
            if self._pending_request is not None and not self._shutdown:
                self._ensure_worker()

    def _stage_current(self, request: dict[str, Any]) -> bool:
        if int(request["auto_revision"]) != self._auto_revision:
            return False
        if request["stage"] == "automatic":
            # A Manual change never invalidates Automatic.
            return True
        return (
            int(request["generation"]) == self._generation
            and int(request["manual_revision"]) == self._manual_revision
            and self._automatic_context is not None
        )

    def _publish_stage_failed(
        self, stage: str, reason: str, blocker: str
    ) -> None:
        """Combined failure must never erase a valid Automatic forecast."""
        self._last_reason = reason
        if stage == "automatic":
            self._automatic_context = None
            bundle = self._blocked_bundle(blocker)
        else:
            bundle = dict(self._cached_bundle)
            bundle["status"] = "blocked"
            bundle["valid"] = False
            bundle["blockers"] = [blocker]
            bundle["combined"] = self._blocked_snapshot(
                blocker, combined=True
            )
        metadata = self._runtime_metadata()
        metadata["planner_worker_active"] = False
        metadata["planner_active_stage"] = None
        bundle.update(metadata)
        for key in ("automatic", "combined"):
            if isinstance(bundle.get(key), dict):
                bundle[key].update(metadata)
        self._cached_bundle = bundle
        self._notify()

    async def _async_compute(
        self, request: dict[str, Any]
    ) -> None:
        stage = str(request["stage"])
        generation = int(request["generation"])
        signature = str(request["request_signature"])
        stop = Event()
        started = time.monotonic()
        diagnostics = PlannerDiagnostics(stage, generation)

        def record_measurement() -> None:
            elapsed = round(time.monotonic() - started, 3)
            self._last_compute_seconds = elapsed
            value = diagnostics.snapshot()
            value["manager_elapsed_seconds"] = elapsed
            if stage == "automatic":
                self._automatic_last_compute_seconds = elapsed
                self._automatic_diagnostics = value
            else:
                self._combined_last_compute_seconds = elapsed
                self._combined_diagnostics = value

        self._active_stage = stage
        self._active_signature = signature
        self._active_generation = generation
        self._active_cancel_event = stop
        self._compute_count += 1
        if stage == "automatic":
            self._automatic_compute_count += 1
        else:
            self._combined_compute_count += 1
        try:
            def compute() -> dict[str, Any]:
                diagnostics.start()
                outcome = "completed"
                try:
                    return measured_compute()
                except PlannerComputeBudgetExceeded:
                    outcome = "budget_exceeded"
                    raise
                except PlannerComputeCancelled:
                    outcome = "cancelled"
                    raise
                except Exception:
                    outcome = "failed"
                    raise
                finally:
                    diagnostics.finish(outcome)

            def measured_compute() -> dict[str, Any]:
                # Independent 20-second work budget per stage, so Combined
                # can never invalidate the already completed Automatic run.
                guard = make_planner_work_guard(stop)
                if stage == "automatic":
                    return compute_planner_bundle(
                        **request["compute_kwargs"],
                        stage="automatic",
                        check_work=guard,
                        diagnostics=diagnostics,
                    )
                return compute_planner_bundle(
                    **request["compute_kwargs"],
                    check_work=guard,
                    diagnostics=diagnostics,
                )

            bundle = await self.hass.async_add_executor_job(compute)
        except PlannerComputeCancelled:
            self._cancel_count += 1
            return
        except PlannerComputeBudgetExceeded as err:
            record_measurement()
            self._budget_exceeded_count += 1
            if not self._shutdown and self._stage_current(request):
                self._last_error = str(err)
                self._publish_stage_failed(
                    stage, str(request["reason"]),
                    "planner_compute_budget_exceeded",
                )
            _LOGGER.warning("DOEMS %s stage work budget exceeded: %s", stage, diagnostics.snapshot())
            return
        except asyncio.CancelledError:
            stop.set()
            raise
        except Exception as err:
            record_measurement()
            if not self._shutdown and self._stage_current(request):
                self._last_error = f"{type(err).__name__}: {err}"
                self._publish_stage_failed(
                    stage, str(request["reason"]), "planner_compute_failed"
                )
            _LOGGER.exception("DOEMS %s stage calculation failed", stage)
            return
        finally:
            record_measurement()
            if self._active_cancel_event is stop:
                self._active_stage = None
                self._active_signature = None
                self._active_generation = None
                self._active_cancel_event = None

        if not self._stage_current(request) or self._shutdown:
            self._stale_discard_count += 1
            return
        if stage == "automatic":
            self._publish_automatic(request, bundle)
        else:
            self._publish_combined(request, bundle)

    def _publish_automatic(
        self, request: dict[str, Any], bundle: dict[str, Any]
    ) -> None:
        automatic = bundle.get("automatic") or {}
        if not automatic.get("valid") or automatic.get("native_slot_count") != 288:
            self._last_error = "automatic_stage_invalid"
            self._publish_stage_failed(
                "automatic", str(request["reason"]),
                "planner_automatic_invalid",
            )
            return
        self._automatic_context = {
            "automatic": automatic,
            "energy_slots": bundle["_prepared_energy_slots"],
            "compute_kwargs": dict(request["compute_kwargs"]),
            "cycle_id": request["cycle_id"],
            "signature": request["request_signature"],
            "auto_revision": self._auto_revision,
        }
        self._automatic_published_generation = int(request["generation"])
        self._last_request_signature = str(request["request_signature"])
        self._last_input_signature = str(
            bundle.get("planner_input_signature") or ""
        ) or None
        self._last_cycle_id = str(request["cycle_id"])
        self._last_reason = str(request["reason"])
        self._last_error = None

        # Publish the new Automatic separately. The previous Combined is
        # retained only until this cycle's Combined replan is ready.
        published = {
            **self._cached_bundle,
            "status": "automatic_ready_combined_pending",
            "valid": False,
            "automatic": automatic,
            "runtime_version": RUNTIME_VERSION,
        }
        self._cached_bundle = published
        self._enqueue_combined("automatic_completed")
        metadata = self._runtime_metadata()
        for key in ("automatic", "combined"):
            if isinstance(published.get(key), dict):
                published[key].update(metadata)
        published.update(metadata)
        self._notify()

    def _publish_combined(
        self, request: dict[str, Any], bundle: dict[str, Any]
    ) -> None:
        combined = bundle.get("combined") or {}
        if not combined.get("valid") or combined.get("native_slot_count") != 288:
            self._last_error = "combined_stage_invalid"
            self._publish_stage_failed(
                "combined", str(request["reason"]),
                "planner_combined_invalid",
            )
            return

        self._published_generation = int(request["generation"])
        self._last_input_signature = str(
            bundle.get("planner_input_signature") or ""
        ) or None
        self._last_cycle_id = str(request["cycle_id"])
        self._last_reason = str(request["reason"])
        self._last_refreshed_at = dt_util.utcnow().isoformat()
        self._last_error = None
        metadata = self._runtime_metadata()
        metadata["planner_worker_active"] = False
        metadata["planner_active_stage"] = None
        metadata["planner_combined_pending"] = False
        automatic = self._automatic_context["automatic"]
        published = {
            "status": "ready",
            "valid": True,
            "blockers": [],
            "automatic": automatic,
            "combined": combined,
            "runtime_version": RUNTIME_VERSION,
        }
        published.update(metadata)
        automatic.update(metadata)
        combined.update(metadata)
        self._cached_bundle = published
        self._notify()

    def snapshot(self, planner: str = "combined") -> dict[str, Any]:
        """Return cache only; entity reads never execute planner policy."""
        if planner == "automatic":
            value = self._cached_bundle.get("automatic")
        else:
            value = self._cached_bundle.get("combined")
        return value if isinstance(value, dict) else {}

    def bundle_snapshot(self) -> dict[str, Any]:
        return self._cached_bundle

