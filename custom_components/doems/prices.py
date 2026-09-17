"""Prices P4 runtime for DOEMS.

The runtime is data-only. It fetches Stroomvoorspeller market data, normalizes
known and forecast prices onto the native 15-minute contract and exposes a
provider-neutral manager consumed by public Home Assistant entities.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any
from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ELECTRICITY_EXPORT_SUPPLIER,
    CONF_ELECTRICITY_EXPORT_TAX,
    CONF_ELECTRICITY_FIXED_SUPPLY_PER_DAY,
    CONF_ELECTRICITY_GRID_PER_DAY,
    CONF_ELECTRICITY_IMPORT_SUPPLIER,
    CONF_ELECTRICITY_IMPORT_TAX,
    CONF_ELECTRICITY_TAX_CREDIT_PER_DAY,
    CONF_GAS_FIXED_SUPPLY_PER_DAY,
    CONF_GAS_GRID_PER_DAY,
    CONF_GAS_MARKET_ENTITY,
    CONF_GAS_PRICES_ENABLED,
    CONF_GAS_SUPPLIER,
    CONF_GAS_TAX,
    CONF_PRICES_RESOLUTION_PREFERENCE,
    CONF_TARIFF_PROFILE_ID,
    CONF_TARIFF_SUPPLIER,
    CONF_TARIFF_VALID_FROM,
    CONF_VAT_PERCENT,
    FORECAST_HORIZON_HOURS,
    FORECAST_SLOTS,
    PRICE_BUFFER_HOURS,
    PRICE_BUFFER_SLOT_COUNT,
    PRICES_PROVIDER,
    PRICES_RESOLUTION_15_MIN,
    PRICES_RESOLUTION_60_MIN,
    PRICES_RESOLUTION_AUTO,
    PRICES_SOURCE_ATTRIBUTION,
    QUARTER_MINUTES,
)
from .prices_model import (
    PricePoint,
    ceil_quarter,
    compose_point,
    deduplicate_price_points,
    expected_quarter_starts,
    floor_quarter,
    select_exact_price_window,
    utc,
)

_LOGGER = logging.getLogger(__name__)

PRICES_URL = "https://stroomvoorspeller.nl/data/prices.json"
FORECAST_URL = "https://stroomvoorspeller.nl/data/forecast.json"
REFRESH_INTERVAL = timedelta(minutes=30)
SOURCE_STALE_AFTER = timedelta(hours=28)

PUBLIC_ENTITY_IDS = (
    "sensor.doems_prices_status",
    "sensor.doems_prices_market_current",
    "sensor.doems_prices_import_current",
    "sensor.doems_prices_export_current",
    "sensor.doems_prices_timeline",
    "sensor.doems_prices_tariff_profile",
    "sensor.doems_prices_gas_market",
    "sensor.doems_prices_gas_all_in",
)


class DOEMSPricesManager:
    """Fetch, normalize and expose the Prices P4 contract."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self.points: list[PricePoint] = []
        self.timeline_slots: list[dict[str, Any]] = []
        self._normalized_points_by_start: dict[datetime, PricePoint] = {}
        self._price_buffer_by_start: dict[datetime, PricePoint] = {}
        self.last_update: datetime | None = None
        self.source_generated_at: str | None = None
        self.forecast_generated_at: str | None = None
        self.status = "not_loaded"
        self.error: str | None = None
        self.has_pt15m = False
        self.pt15m_count = 0
        self.pt15m_first_time: datetime | None = None
        self.pt15m_last_time: datetime | None = None
        self.known_count = 0
        self.forecast_count = 0
        self.current_source = "missing"
        self.price_buffer_start: datetime | None = None
        self.price_buffer_end: datetime | None = None
        self.price_buffer_valid_slots = 0
        self.price_buffer_missing_slots = PRICE_BUFFER_SLOT_COUNT
        self.price_buffer_duplicate_slots = 0
        self.price_buffer_missing_starts: list[datetime] = []
        self.timeline_start: datetime | None = None
        self.timeline_end: datetime | None = None
        self.timeline_missing_starts: list[datetime] = []

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.entry.options)

    def _num(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.entry.options.get(key, default))
        except (TypeError, ValueError):
            return default

    @property
    def resolution_preference(self) -> str:
        value = str(self.entry.options.get(CONF_PRICES_RESOLUTION_PREFERENCE, PRICES_RESOLUTION_AUTO))
        if value not in {PRICES_RESOLUTION_AUTO, PRICES_RESOLUTION_15_MIN, PRICES_RESOLUTION_60_MIN}:
            return PRICES_RESOLUTION_AUTO
        return value

    @property
    def gas_enabled(self) -> bool:
        return bool(self.entry.options.get(CONF_GAS_PRICES_ENABLED, False))

    @property
    def gas_market_entity(self) -> str | None:
        value = self.entry.options.get(CONF_GAS_MARKET_ENTITY)
        return str(value) if value else None

    @property
    def gas_market_price(self) -> float | None:
        if not self.gas_enabled or not self.gas_market_entity:
            return None
        state = self.hass.states.get(self.gas_market_entity)
        if state is None or state.state in {"unknown", "unavailable", "none", "None", ""}:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    @property
    def gas_variable_addon(self) -> float:
        return self._num(CONF_GAS_SUPPLIER) + self._num(CONF_GAS_TAX)

    @property
    def gas_all_in_price(self) -> float | None:
        market = self.gas_market_price
        return None if market is None else round(market + self.gas_variable_addon, 6)

    @property
    def tariff_snapshot(self) -> dict[str, Any]:
        return {
            "profile_id": self.entry.options.get(CONF_TARIFF_PROFILE_ID, "unconfigured"),
            "supplier": self.entry.options.get(CONF_TARIFF_SUPPLIER, "unconfigured"),
            "valid_from": self.entry.options.get(CONF_TARIFF_VALID_FROM) or None,
            "vat_percent": self._num(CONF_VAT_PERCENT, 21.0),
            "electricity_import_supplier_incl_vat": self._num(CONF_ELECTRICITY_IMPORT_SUPPLIER),
            "electricity_import_tax_incl_vat": self._num(CONF_ELECTRICITY_IMPORT_TAX),
            "electricity_export_supplier_incl_vat": self._num(CONF_ELECTRICITY_EXPORT_SUPPLIER),
            "electricity_export_tax_incl_vat": self._num(CONF_ELECTRICITY_EXPORT_TAX),
            "electricity_fixed_supply_per_day": self._num(CONF_ELECTRICITY_FIXED_SUPPLY_PER_DAY),
            "electricity_grid_per_day": self._num(CONF_ELECTRICITY_GRID_PER_DAY),
            "electricity_tax_credit_per_day": self._num(CONF_ELECTRICITY_TAX_CREDIT_PER_DAY),
            "gas_prices_enabled": self.gas_enabled,
            "gas_supplier_incl_vat": self._num(CONF_GAS_SUPPLIER),
            "gas_tax_incl_vat": self._num(CONF_GAS_TAX),
            "gas_fixed_supply_per_day": self._num(CONF_GAS_FIXED_SUPPLY_PER_DAY),
            "gas_grid_per_day": self._num(CONF_GAS_GRID_PER_DAY),
            "fixed_daily_costs_excluded_from_slot_ranking": True,
            "immutable_history_rule": True,
            "future_profile_changes_do_not_reprice_history": True,
        }

    async def async_setup(self) -> None:
        await self.async_refresh()
        self._unsubs.append(async_track_time_interval(self.hass, self._scheduled_refresh, REFRESH_INTERVAL))
        if self.gas_enabled and self.gas_market_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    [self.gas_market_entity],
                    self._gas_source_changed,
                )
            )

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self.listeners.clear()
        for entity_id in PUBLIC_ENTITY_IDS:
            self.hass.states.async_remove(entity_id)

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self.listeners.append(listener)

        @callback
        def remove_listener() -> None:
            if listener in self.listeners:
                self.listeners.remove(listener)

        return remove_listener

    @callback
    def _notify(self) -> None:
        for listener in list(self.listeners):
            listener()

    @callback
    def _scheduled_refresh(self, _now: datetime) -> None:
        self.hass.async_create_task(self.async_refresh())

    @callback
    def _gas_source_changed(self, _event: Event) -> None:
        self._publish_states()
        self._notify()

    async def async_refresh(self) -> None:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(PRICES_URL, timeout=20) as response:
                response.raise_for_status()
                prices_payload = await response.json()
            async with session.get(FORECAST_URL, timeout=20) as response:
                response.raise_for_status()
                forecast_payload = await response.json()

            self._build_timeline(prices_payload, forecast_payload)
            self.last_update = dt_util.utcnow()
            self.source_generated_at = prices_payload.get("generated_at") or prices_payload.get("generated")
            self.forecast_generated_at = forecast_payload.get("generated_at") or forecast_payload.get("generated")
            self.error = None
            if len(self.points) == FORECAST_SLOTS and not self.timeline_missing_starts:
                self.status = "ok"
            elif self.points:
                self.status = "partial"
            else:
                self.status = "empty"
        except Exception as err:
            self.error = f"{type(err).__name__}: {err}"
            self.status = "error"
            _LOGGER.warning("DOEMS Prices refresh failed: %s", self.error)
        self._publish_states()
        self._notify()

    def _build_timeline(self, prices_payload: dict[str, Any], forecast_payload: dict[str, Any]) -> None:
        pt15_raw = prices_payload.get("prices_15m") or []
        source_has_pt15m = prices_payload.get("has_pt15m") is True and bool(pt15_raw)
        use_pt15m = source_has_pt15m and self.resolution_preference != PRICES_RESOLUTION_60_MIN
        use_hourly_known = self.resolution_preference != PRICES_RESOLUTION_15_MIN
        self.has_pt15m = source_has_pt15m

        known: dict[datetime, PricePoint] = {}
        if use_hourly_known:
            for item in prices_payload.get("prices") or []:
                start = self._parse_time(item.get("time") or item.get("timestamp") or item.get("start"))
                market = self._eur_mwh_to_kwh(item.get("price"))
                if start is None or market is None:
                    continue
                for quarter in range(4):
                    q_start = start + timedelta(minutes=quarter * QUARTER_MINUTES)
                    known[utc(q_start)] = self._compose_point(q_start, market, "known_hourly_fallback", 60)

        pt15_times: list[datetime] = []
        if use_pt15m:
            for item in pt15_raw:
                start = self._parse_time(item.get("time") or item.get("timestamp") or item.get("start"))
                market = self._eur_mwh_to_kwh(item.get("price"))
                if start is None or market is None:
                    continue
                start = utc(start)
                known[start] = self._compose_point(start, market, "known_pt15m", 15)
                pt15_times.append(start)
        self.pt15m_count = len(pt15_times)
        self.pt15m_first_time = min(pt15_times) if pt15_times else None
        self.pt15m_last_time = max(pt15_times) if pt15_times else None
        self.known_count = len(known)

        forecast_generated = forecast_payload.get("generated_at") or forecast_payload.get("generated")
        future: dict[datetime, PricePoint] = {}
        for item in forecast_payload.get("forecasts") or []:
            start = self._parse_time(item.get("time") or item.get("timestamp") or item.get("start"))
            predicted = self._eur_mwh_to_kwh(item.get("predicted"))
            if start is None or predicted is None:
                continue
            for quarter in range(4):
                q_start = utc(start + timedelta(minutes=quarter * QUARTER_MINUTES))
                point = self._compose_point(q_start, predicted, "forecast_hour", 60)
                point.lower_ex_vat = self._eur_mwh_to_kwh(item.get("lower"))
                point.upper_ex_vat = self._eur_mwh_to_kwh(item.get("upper"))
                point.forecast_generated_at = forecast_generated
                point.uncertainty_pct = self._safe_float(item.get("uncertainty_pct"))
                point.regime = item.get("regime")
                future[q_start] = point
        self.forecast_count = len(future)

        indexed, duplicate_count = deduplicate_price_points([*future.values(), *known.values()])
        self._normalized_points_by_start = indexed
        self.price_buffer_duplicate_slots = duplicate_count

        now = dt_util.utcnow()
        buffer_start = floor_quarter(now)
        buffer_points, buffer_missing = select_exact_price_window(indexed, start=buffer_start, slot_count=PRICE_BUFFER_SLOT_COUNT)
        self.price_buffer_start = buffer_start
        self.price_buffer_end = buffer_start + timedelta(hours=PRICE_BUFFER_HOURS)
        self.price_buffer_valid_slots = len(buffer_points)
        self.price_buffer_missing_slots = len(buffer_missing)
        self.price_buffer_missing_starts = buffer_missing
        self._price_buffer_by_start = {utc(point.start): point for point in buffer_points}

        public_start = ceil_quarter(now)
        expected = expected_quarter_starts(public_start, FORECAST_SLOTS)
        public_points, missing = select_exact_price_window(self._price_buffer_by_start, start=public_start, slot_count=FORECAST_SLOTS)
        self.points = public_points
        self.timeline_start = public_start
        self.timeline_end = public_start + timedelta(hours=FORECAST_HORIZON_HOURS)
        self.timeline_missing_starts = missing
        self.timeline_slots = []
        for start in expected:
            point = self._price_buffer_by_start.get(start)
            if point is None:
                self.timeline_slots.append({"time": start.isoformat(), "market_ex_vat": None, "market_incl_vat": None, "import_all_in": None, "export_all_in": None, "kind": "missing", "source_resolution_minutes": None})
            else:
                self.timeline_slots.append(point.as_dict())

        current = self._normalized_points_by_start.get(floor_quarter(now))
        self.current_source = current.kind if current is not None and current.kind.startswith("known_") else "missing"

    def _compose_point(self, start: datetime, market_ex_vat: float, kind: str, source_resolution: int) -> PricePoint:
        return compose_point(
            start,
            market_ex_vat,
            kind=kind,
            source_resolution_minutes=source_resolution,
            vat_percent=self._num(CONF_VAT_PERCENT, 21.0),
            import_supplier_incl_vat=self._num(CONF_ELECTRICITY_IMPORT_SUPPLIER),
            import_tax_incl_vat=self._num(CONF_ELECTRICITY_IMPORT_TAX),
            export_supplier_incl_vat=self._num(CONF_ELECTRICITY_EXPORT_SUPPLIER),
            export_tax_incl_vat=self._num(CONF_ELECTRICITY_EXPORT_TAX),
        )

    @property
    def current_point(self) -> PricePoint | None:
        point = self._normalized_points_by_start.get(floor_quarter(dt_util.utcnow()))
        if point is None or not point.kind.startswith("known_"):
            return None
        return point

    @property
    def freshness(self) -> str:
        if self.last_update is None:
            return "not_loaded"
        return "stale" if dt_util.utcnow() - self.last_update > SOURCE_STALE_AFTER else "fresh"

    @property
    def attributes(self) -> dict[str, Any]:
        return {
            "provider": PRICES_PROVIDER,
            "attribution": PRICES_SOURCE_ATTRIBUTION,
            "status": self.status,
            "freshness": self.freshness,
            "error": self.error,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "prices_generated_at": self.source_generated_at,
            "forecast_generated_at": self.forecast_generated_at,
            "resolution_preference": self.resolution_preference,
            "native_resolution_minutes": QUARTER_MINUTES,
            "horizon_hours": FORECAST_HORIZON_HOURS,
            "expected_slots": FORECAST_SLOTS,
            "timeline_slots": len(self.timeline_slots),
            "timeline_valid_slots": len(self.points),
            "timeline_missing_slots": len(self.timeline_missing_starts),
            "timeline_start": self.timeline_start.isoformat() if self.timeline_start else None,
            "timeline_end": self.timeline_end.isoformat() if self.timeline_end else None,
            "current_price_source": self.current_source,
            "has_pt15m": self.has_pt15m,
            "pt15m_slots": self.pt15m_count,
            "pt15m_first_time": self.pt15m_first_time.isoformat() if self.pt15m_first_time else None,
            "pt15m_last_time": self.pt15m_last_time.isoformat() if self.pt15m_last_time else None,
            "known_slots": self.known_count,
            "forecast_slots": self.forecast_count,
            "price_buffer_hours": PRICE_BUFFER_HOURS,
            "price_buffer_expected_slots": PRICE_BUFFER_SLOT_COUNT,
            "price_buffer_valid_slots": self.price_buffer_valid_slots,
            "price_buffer_missing_slots": self.price_buffer_missing_slots,
            "price_buffer_duplicate_slots": self.price_buffer_duplicate_slots,
            "price_buffer_start": self.price_buffer_start.isoformat() if self.price_buffer_start else None,
            "price_buffer_end": self.price_buffer_end.isoformat() if self.price_buffer_end else None,
            "known_over_forecast": True,
            "current_never_uses_forecast": True,
            "import_export_separate": True,
            "physical_execution_authority": False,
        }

    def _publish_states(self) -> None:
        common = self.attributes
        point = self.current_point
        point_attrs = point.as_dict() if point else {}
        self.hass.states.async_set("sensor.doems_prices_status", self.status, common)
        self.hass.states.async_set("sensor.doems_prices_market_current", point.market_incl_vat if point else None, {**common, **point_attrs, "unit_of_measurement": "EUR/kWh", "price_basis": "market_incl_vat"})
        self.hass.states.async_set("sensor.doems_prices_import_current", point.import_all_in if point else None, {**common, **point_attrs, "unit_of_measurement": "EUR/kWh", "price_basis": "marginal_import_all_in"})
        self.hass.states.async_set("sensor.doems_prices_export_current", point.export_all_in if point else None, {**common, **point_attrs, "unit_of_measurement": "EUR/kWh", "price_basis": "marginal_export_all_in"})
        self.hass.states.async_set("sensor.doems_prices_timeline", len(self.points), {**common, "unit_of_measurement": "slots", "point_format": "{time, market_ex_vat, market_incl_vat, import_all_in, export_all_in, kind, source_resolution_minutes, ...}", "points": self.timeline_slots, "recorder_recommendation": "exclude this timeline sensor from Recorder"})
        tariff = self.tariff_snapshot
        self.hass.states.async_set("sensor.doems_prices_tariff_profile", tariff.get("profile_id") or "unconfigured", tariff)
        if self.gas_enabled:
            self.hass.states.async_set("sensor.doems_prices_gas_market", self.gas_market_price, {"unit_of_measurement": "EUR/m3", "source": "configured_home_assistant_entity", "source_entity": self.gas_market_entity, "physical_execution_authority": False})
            self.hass.states.async_set("sensor.doems_prices_gas_all_in", self.gas_all_in_price, {"unit_of_measurement": "EUR/m3", "market_price": self.gas_market_price, "variable_addon_incl_vat": round(self.gas_variable_addon, 6), "gas_supplier_incl_vat": tariff.get("gas_supplier_incl_vat"), "gas_tax_incl_vat": tariff.get("gas_tax_incl_vat"), "gas_fixed_supply_per_day": tariff.get("gas_fixed_supply_per_day"), "gas_grid_per_day": tariff.get("gas_grid_per_day"), "tariff_profile_id": tariff.get("profile_id"), "physical_execution_authority": False})
        else:
            self.hass.states.async_remove("sensor.doems_prices_gas_market")
            self.hass.states.async_remove("sensor.doems_prices_gas_all_in")

    @staticmethod
    def _eur_mwh_to_kwh(value: Any) -> float | None:
        parsed = DOEMSPricesManager._safe_float(value)
        return parsed / 1000.0 if parsed is not None else None

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = dt_util.parse_datetime(str(value))
        except (TypeError, ValueError):
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.UTC)
        return parsed
