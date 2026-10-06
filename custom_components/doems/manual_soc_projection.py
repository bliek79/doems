"""Runtime bridge for the DOEMS R3 manual SOC projection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import callback

from .battery_contract import DOEMSBatteryInputContract
from .energy_coordinator import DOEMSEnergyCoordinator
from .manual_plan_model import PLAN_SLOT_COUNT
from .manual_plan_store import DOEMSManualPlanStore
from .manual_soc_projection_model import project_manual_soc
from .prices import DOEMSPricesManager
from .solar_forecast import SolarForecastManager


class DOEMSManualSOCProjection:
    """Combine R1 battery input, forecasts and R2 manual commitments."""

    def __init__(
        self,
        *,
        energy: DOEMSEnergyCoordinator | None,
        solar: SolarForecastManager | None,
        prices: DOEMSPricesManager | None,
        battery: DOEMSBatteryInputContract | None,
        plans: DOEMSManualPlanStore,
    ) -> None:
        self.energy = energy
        self.solar = solar
        self.prices = prices
        self.battery = battery
        self.plans = plans
        self._listeners: list[Callable[[], None]] = []
        self._source_unsubs: list[Callable[[], None]] = []

    async def async_setup(self) -> None:
        for source in (self.energy, self.solar, self.prices, self.battery):
            if source is not None and hasattr(source, "async_add_listener"):
                self._source_unsubs.append(source.async_add_listener(self._source_changed))
        self._source_unsubs.append(self.plans.add_listener(self._source_changed))

    async def async_shutdown(self) -> None:
        for unsub in self._source_unsubs:
            unsub()
        self._source_unsubs.clear()
        self._listeners.clear()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @callback
    def _source_changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def _blocked(self, *blockers: str) -> dict[str, Any]:
        return {
            "status": "blocked",
            "valid": False,
            "blockers": list(blockers),
            "native_slots": [],
            "hourly_plan": [],
            "native_slot_count": 0,
            "clock_hour_bucket_count": 0,
            "manual_commitment_count": 0,
            "manual_commitment_slots": [],
            "start_soc_percent": None,
            "end_soc_percent": None,
            "physical_execution_authority": False,
            "automatic_planner_active": False,
            "scheduler_active": False,
            "mode": "manual_projection_only",
        }

    def snapshot(self) -> dict[str, Any]:
        if self.energy is None:
            return self._blocked("energy_forecast_unavailable")
        if self.solar is None:
            return self._blocked("solar_forecast_unavailable")
        if self.battery is None:
            return self._blocked("battery_input_contract_unavailable")

        battery = self.battery.snapshot()
        if battery.get("status") != "ready" or battery.get("ready_for_soc_projection") is not True:
            inherited = [str(value) for value in battery.get("blockers", [])]
            return self._blocked("battery_input_not_ready", *inherited)

        soc = battery.get("soc_percent")
        capacity = battery.get("capacity_kwh")
        if soc is None or capacity is None:
            return self._blocked("battery_soc_or_capacity_missing")

        energy_slots = [
            {
                "start": slot.start.isoformat(),
                "end": slot.end.isoformat(),
                "home_kwh": slot.energy_kwh,
            }
            for slot in self.energy.forecast()
        ]
        solar_slots = [
            {
                "start": point.start.isoformat(),
                "solar_kwh": point.total_kwh,
            }
            for point in self.solar.points
        ]
        plans = [
            {
                **self.plans.get_plan(slot),
                "slot": slot,
            }
            for slot in range(1, PLAN_SLOT_COUNT + 1)
        ]
        price_by_start = None
        if self.prices is not None:
            price_by_start = {
                str(item.get("time")): item
                for item in self.prices.timeline_slots
                if isinstance(item, dict) and item.get("time")
            }

        return project_manual_soc(
            energy_slots=energy_slots,
            solar_slots=solar_slots,
            plans=plans,
            start_soc_percent=float(soc),
            capacity_kwh=float(capacity),
            price_by_start=price_by_start,
        )
