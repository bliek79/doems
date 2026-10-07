"""Runtime bridge for the DOEMS R5 automatic planner shadow."""

from __future__ import annotations
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback

from .automatic_planner_model import build_automatic_plan
from .battery_contract import DOEMSBatteryInputContract
from .const import (
    CONF_MAX_CHARGE_POWER_W, CONF_MAX_DISCHARGE_POWER_W,
    CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH, CONF_PEAK_SALE_THRESHOLD_EUR_PER_KWH,
    CONF_SOFTWARE_RESERVE_PERCENT, DEFAULT_MAX_CHARGE_POWER_W,
    DEFAULT_MAX_DISCHARGE_POWER_W, DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
    DEFAULT_PEAK_SALE_THRESHOLD_EUR_PER_KWH, DEFAULT_SOFTWARE_RESERVE_PERCENT,
)
from .energy_coordinator import DOEMSEnergyCoordinator
from .manual_plan_model import PLAN_SLOT_COUNT
from .manual_plan_store import DOEMSManualPlanStore
from .prices import DOEMSPricesManager
from .solar_forecast import SolarForecastManager


class DOEMSAutomaticPlanner:
    """Combine forecasts, live battery input and manual commitments in shadow."""

    def __init__(self, *, entry: ConfigEntry, energy: DOEMSEnergyCoordinator | None,
                 solar: SolarForecastManager | None, prices: DOEMSPricesManager | None,
                 battery: DOEMSBatteryInputContract | None, plans: DOEMSManualPlanStore) -> None:
        self.entry=entry; self.energy=energy; self.solar=solar; self.prices=prices
        self.battery=battery; self.plans=plans
        self._listeners: list[Callable[[], None]]=[]; self._source_unsubs: list[Callable[[], None]]=[]

    async def async_setup(self) -> None:
        for source in (self.energy,self.solar,self.prices,self.battery):
            if source is not None and hasattr(source,"async_add_listener"):
                self._source_unsubs.append(source.async_add_listener(self._source_changed))
        self._source_unsubs.append(self.plans.add_listener(self._source_changed))

    async def async_shutdown(self) -> None:
        for unsub in self._source_unsubs: unsub()
        self._source_unsubs.clear(); self._listeners.clear()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        @callback
        def _remove() -> None:
            if listener in self._listeners: self._listeners.remove(listener)
        return _remove

    @callback
    def _source_changed(self) -> None:
        for listener in tuple(self._listeners): listener()

    def _blocked(self,*blockers:str)->dict[str,Any]:
        return {"status":"blocked","valid":False,"blockers":list(blockers),"native_slots":[],
                "hourly_plan":[],"candidates":[],"candidate_count":0,"native_slot_count":0,
                "clock_hour_bucket_count":0,"automatic_planner_active":True,
                "automatic_plan_store_writes":False,"scheduler_active":False,
                "safety_prestart_active":False,"execution_enabled":False,
                "physical_execution_authority":False,"mode":"automatic_planner_shadow",
                "observational_only":True}

    def snapshot(self)->dict[str,Any]:
        if self.energy is None: return self._blocked("energy_forecast_unavailable")
        if self.solar is None: return self._blocked("solar_forecast_unavailable")
        if self.prices is None: return self._blocked("prices_forecast_unavailable")
        if self.battery is None: return self._blocked("battery_input_contract_unavailable")
        battery=self.battery.snapshot()
        if battery.get("status")!="ready" or battery.get("ready_for_soc_projection") is not True:
            return self._blocked("battery_input_not_ready",*[str(v) for v in battery.get("blockers",[])])
        soc=battery.get("soc_percent"); capacity=battery.get("capacity_kwh")
        if soc is None or capacity is None: return self._blocked("battery_soc_or_capacity_missing")
        energy_slots=[{"start":s.start.isoformat(),"end":s.end.isoformat(),"home_kwh":s.energy_kwh} for s in self.energy.forecast()]
        solar_slots=[{"start":p.start.isoformat(),"solar_kwh":p.total_kwh} for p in self.solar.points]
        plans=[{**self.plans.get_plan(slot),"slot":slot} for slot in range(1,PLAN_SLOT_COUNT+1)]
        price_by_start={str(x.get("time")):x for x in self.prices.timeline_slots if isinstance(x,dict) and x.get("time")}
        o=self.entry.options
        return build_automatic_plan(
            energy_slots=energy_slots,solar_slots=solar_slots,plans=plans,
            start_soc_percent=float(soc),capacity_kwh=float(capacity),price_by_start=price_by_start,
            software_reserve_percent=float(o.get(CONF_SOFTWARE_RESERVE_PERCENT,DEFAULT_SOFTWARE_RESERVE_PERCENT)),
            max_charge_power_w=float(o.get(CONF_MAX_CHARGE_POWER_W,DEFAULT_MAX_CHARGE_POWER_W)),
            max_discharge_power_w=float(o.get(CONF_MAX_DISCHARGE_POWER_W,DEFAULT_MAX_DISCHARGE_POWER_W)),
            minimum_trade_margin_eur_per_kwh=float(o.get(CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH)),
            peak_sale_threshold_eur_per_kwh=float(o.get(CONF_PEAK_SALE_THRESHOLD_EUR_PER_KWH,DEFAULT_PEAK_SALE_THRESHOLD_EUR_PER_KWH)),
        )
