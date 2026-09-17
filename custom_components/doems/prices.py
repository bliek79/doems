"""Prices P4.1 runtime for DOEMS."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from aiohttp import ClientError

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
    CONF_PRICES_FORECAST_ENABLED,
    CONF_PRICES_PROVIDER,
    CONF_PRICES_RESOLUTION,
    CONF_TARIFF_PROFILE_ID,
    CONF_TARIFF_SUPPLIER,
    CONF_TARIFF_VALID_FROM,
    CONF_VAT_PERCENT,
    FORECAST_SLOTS,
    PRICE_BUFFER_HOURS,
    PRICE_BUFFER_SLOT_COUNT,
    PRICES_FORECAST_URL,
    PRICES_PROVIDER_STROOMVOORSPELLER,
    PRICES_REFRESH_MINUTES,
    PRICES_RESOLUTION_15_MIN,
    PRICES_RESOLUTION_60_MIN,
    PRICES_RESOLUTION_AUTO,
    PRICES_SOURCE_ATTRIBUTION,
    PRICES_STALE_AFTER_HOURS,
    PRICES_URL,
    QUARTER_MINUTES,
)
from .prices_model import (
    PricePoint,
    canonical_utc,
    compose_point,
    deduplicate_price_points,
    floor_quarter,
    select_exact_price_window,
)

_LOGGER = logging.getLogger(__name__)


class DOEMSPricesManager:
    """Fetch and normalize electricity prices without controlling anything."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self.points: list[PricePoint] = []
        self._buffer_by_start: dict[datetime, PricePoint] = {}
        self.last_attempt: datetime | None = None
        self.last_successful_update: datetime | None = None
        self.last_error: str | None = None
        self.source_generated_at: str | None = None
        self.forecast_generated_at: str | None = None
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

    @property
    def enabled(self) -> bool:
        return bool(self.entry.options.get(CONF_PRICES_FORECAST_ENABLED, False))

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.entry.options)

    @property
    def provider(self) -> str:
        return str(
            self.entry.options.get(
                CONF_PRICES_PROVIDER, PRICES_PROVIDER_STROOMVOORSPELLER
            )
        )

    @property
    def resolution_preference(self) -> str:
        return str(
            self.entry.options.get(CONF_PRICES_RESOLUTION, PRICES_RESOLUTION_AUTO)
        )

    @property
    def gas_enabled(self) -> bool:
        return bool(self.entry.options.get(CONF_GAS_PRICES_ENABLED, False))

    def _num(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.entry.options.get(key, default))
        except (TypeError, ValueError):
            return default

    @property
    def tariff_snapshot(self) -> dict[str, Any]:
        return {
            "profile_id": str(self.entry.options.get(CONF_TARIFF_PROFILE_ID, "default")),
            "supplier": str(self.entry.options.get(CONF_TARIFF_SUPPLIER, "unconfigured")),
            "valid_from": self.entry.options.get(CONF_TARIFF_VALID_FROM),
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
            "immutable_history_rule": True,
            "future_profile_changes_do_not_reprice_history": True,
        }

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
    def gas_all_in_price(self) -> float | None:
        market = self.gas_market_price
        if market is None:
            return None
        return round(
            market + self._num(CONF_GAS_SUPPLIER) + self._num(CONF_GAS_TAX),
            6,
        )

    @property
    def age_minutes(self) -> float | None:
        if self.last_successful_update is None:
            return None
        return round(
            max(
                0.0,
                (dt_util.utcnow() - self.last_successful_update).total_seconds() / 60.0,
            ),
            1,
        )

    @property
    def freshness(self) -> str:
        if self.last_successful_update is None:
            return "not_loaded"
        if (self.age_minutes or 0.0) >= PRICES_STALE_AFTER_HOURS * 60:
            return "stale"
        return "fresh"

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.last_successful_update is None:
            return "error" if self.last_error else "not_loaded"
        if self.freshness == "stale" or self.last_error:
            return "stale"
        if len(self.points) == FORECAST_SLOTS:
            return "ok"
        if self.points:
            return "partial"
        return "empty"

    async def async_setup(self) -> None:
        if not self.enabled:
            self._notify()
            return
        await self.async_refresh()
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._scheduled_refresh,
                timedelta(minutes=PRICES_REFRESH_MINUTES),
            )
        )
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
    def _scheduled_refresh(self, _now: datetime) -> None:
        self.hass.async_create_task(self.async_refresh())

    @callback
    def _gas_source_changed(self, _event: Event) -> None:
        self._notify()

    async def async_refresh(self) -> None:
        """Fetch both provider payloads and retain the last valid timeline on failure."""
        if not self.enabled:
            return
        if self.provider != PRICES_PROVIDER_STROOMVOORSPELLER:
            self.last_error = "unsupported_provider"
            self._notify()
            return

        self.last_attempt = dt_util.utcnow()
        try:
            session = async_get_clientsession(self.hass)
            prices_response, forecast_response = await asyncio.gather(
                session.get(PRICES_URL, timeout=20),
                session.get(PRICES_FORECAST_URL, timeout=20),
            )
            async with prices_response:
                prices_response.raise_for_status()
                prices_payload = await prices_response.json()
            async with forecast_response:
                forecast_response.raise_for_status()
                forecast_payload = await forecast_response.json()
            self._apply_payloads(prices_payload, forecast_payload)
            self.last_successful_update = dt_util.utcnow()
            self.last_error = None
        except (ClientError, asyncio.TimeoutError, ValueError, TypeError, KeyError) as err:
            self.last_error = f"{type(err).__name__}: {err}"
            _LOGGER.warning("DOEMS Prices refresh failed: %s", self.last_error)
        self._notify()

    def _apply_payloads(
        self,
        prices_payload: dict[str, Any],
        forecast_payload: dict[str, Any],
    ) -> None:
        if not isinstance(prices_payload, dict) or not isinstance(forecast_payload, dict):
            raise ValueError("invalid_provider_payload")

        self.source_generated_at = prices_payload.get("generated_at") or prices_payload.get("generated")
        self.forecast_generated_at = forecast_payload.get("generated_at") or forecast_payload.get("generated")

        hourly_known: list[PricePoint] = []
        for item in prices_payload.get("prices") or []:
            if not isinstance(item, dict):
                continue
            start = self._parse_time(item.get("time") or item.get("timestamp") or item.get("start"))
            market = self._eur_mwh_to_kwh(item.get("price"))
            if start is None or market is None:
                continue
            for quarter in range(4):
                hourly_known.append(
                    self._compose_point(
                        start + timedelta(minutes=quarter * QUARTER_MINUTES),
                        market,
                        "known_hourly_fallback",
                        60,
                    )
                )

        pt15_raw = prices_payload.get("prices_15m") or []
        provider_has_pt15m = prices_payload.get("has_pt15m") is True and bool(pt15_raw)
        pt15_known: list[PricePoint] = []
        pt15_times: list[datetime] = []
        if provider_has_pt15m and self.resolution_preference != PRICES_RESOLUTION_60_MIN:
            for item in pt15_raw:
                if not isinstance(item, dict):
                    continue
                start = self._parse_time(item.get("time") or item.get("timestamp") or item.get("start"))
                market = self._eur_mwh_to_kwh(item.get("price"))
                if start is None or market is None:
                    continue
                pt15_known.append(self._compose_point(start, market, "known_pt15m", 15))
                pt15_times.append(start)

        self.has_pt15m = provider_has_pt15m
        self.pt15m_count = len(pt15_known)
        self.pt15m_first_time = min(pt15_times) if pt15_times else None
        self.pt15m_last_time = max(pt15_times) if pt15_times else None

        known_points = hourly_known
        if self.resolution_preference in {PRICES_RESOLUTION_AUTO, PRICES_RESOLUTION_15_MIN}:
            known_points = [*hourly_known, *pt15_known]
        self.known_count = len(known_points)

        future: list[PricePoint] = []
        for item in forecast_payload.get("forecasts") or []:
            if not isinstance(item, dict):
                continue
            start = self._parse_time(item.get("time") or item.get("timestamp") or item.get("start"))
            predicted = self._eur_mwh_to_kwh(item.get("predicted"))
            if start is None or predicted is None:
                continue
            for quarter in range(4):
                point = self._compose_point(
                    start + timedelta(minutes=quarter * QUARTER_MINUTES),
                    predicted,
                    "forecast_hour",
                    60,
                )
                point.lower_ex_vat = self._eur_mwh_to_kwh(item.get("lower"))
                point.upper_ex_vat = self._eur_mwh_to_kwh(item.get("upper"))
                point.forecast_generated_at = self.forecast_generated_at
                point.uncertainty_pct = self._safe_float(item.get("uncertainty_pct"))
                point.regime = item.get("regime")
                future.append(point)
        self.forecast_count = len(future)

        indexed, duplicates = deduplicate_price_points([*future, *known_points])
        current_quarter = floor_quarter(dt_util.utcnow())
        buffer_points, missing = select_exact_price_window(
            indexed,
            start=current_quarter,
            slot_count=PRICE_BUFFER_SLOT_COUNT,
        )
        self.price_buffer_start = canonical_utc(current_quarter)
        self.price_buffer_end = self.price_buffer_start + timedelta(hours=PRICE_BUFFER_HOURS)
        self.price_buffer_valid_slots = len(buffer_points)
        self.price_buffer_missing_slots = len(missing)
        self.price_buffer_duplicate_slots = duplicates
        self.price_buffer_missing_starts = missing
        self._buffer_by_start = {canonical_utc(point.start): point for point in buffer_points}

        self.points, _missing_public = select_exact_price_window(
            self._buffer_by_start,
            start=current_quarter,
            slot_count=FORECAST_SLOTS,
        )
        current = self.current_point
        self.current_source = current.kind if current else "missing"

    def _compose_point(
        self,
        start: datetime,
        market_ex_vat: float,
        kind: str,
        source_resolution_minutes: int,
    ) -> PricePoint:
        return compose_point(
            start=start,
            market_ex_vat=market_ex_vat,
            kind=kind,
            source_resolution_minutes=source_resolution_minutes,
            vat_percent=self._num(CONF_VAT_PERCENT, 21.0),
            import_supplier_incl_vat=self._num(CONF_ELECTRICITY_IMPORT_SUPPLIER),
            import_tax_incl_vat=self._num(CONF_ELECTRICITY_IMPORT_TAX),
            export_supplier_incl_vat=self._num(CONF_ELECTRICITY_EXPORT_SUPPLIER),
            export_tax_incl_vat=self._num(CONF_ELECTRICITY_EXPORT_TAX),
        )

    @property
    def current_point(self) -> PricePoint | None:
        now = canonical_utc(dt_util.utcnow())
        for point in self.points:
            start = canonical_utc(point.start)
            if start <= now < start + timedelta(minutes=QUARTER_MINUTES):
                return point
        return None

    @property
    def attributes(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "freshness": self.freshness,
            "provider": self.provider,
            "source_attribution": PRICES_SOURCE_ATTRIBUTION,
            "resolution_preference": self.resolution_preference,
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
            "last_successful_update": self.last_successful_update.isoformat() if self.last_successful_update else None,
            "age_minutes": self.age_minutes,
            "last_error": self.last_error,
            "prices_generated_at": self.source_generated_at,
            "forecast_generated_at": self.forecast_generated_at,
            "has_pt15m": self.has_pt15m,
            "pt15m_slots": self.pt15m_count,
            "pt15m_first_time": self.pt15m_first_time.isoformat() if self.pt15m_first_time else None,
            "pt15m_last_time": self.pt15m_last_time.isoformat() if self.pt15m_last_time else None,
            "known_slots": self.known_count,
            "forecast_slots": self.forecast_count,
            "timeline_slots": len(self.points),
            "resolution_minutes": QUARTER_MINUTES,
            "horizon_hours": 72,
            "slot_count": FORECAST_SLOTS,
            "price_buffer_hours": PRICE_BUFFER_HOURS,
            "price_buffer_expected_slots": PRICE_BUFFER_SLOT_COUNT,
            "price_buffer_valid_slots": self.price_buffer_valid_slots,
            "price_buffer_missing_slots": self.price_buffer_missing_slots,
            "price_buffer_duplicate_slots": self.price_buffer_duplicate_slots,
            "price_buffer_start": self.price_buffer_start.isoformat() if self.price_buffer_start else None,
            "price_buffer_end": self.price_buffer_end.isoformat() if self.price_buffer_end else None,
            "price_buffer_first_missing": self.price_buffer_missing_starts[0].isoformat() if self.price_buffer_missing_starts else None,
            "price_buffer_last_missing": self.price_buffer_missing_starts[-1].isoformat() if self.price_buffer_missing_starts else None,
            "current_price_source": self.current_source,
            "tariff_profile_id": self.tariff_snapshot["profile_id"],
            "physical_execution_authority": False,
        }

    @staticmethod
    def _eur_mwh_to_kwh(value: Any) -> float | None:
        number = DOEMSPricesManager._safe_float(value)
        return number / 1000.0 if number is not None else None

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
        return canonical_utc(parsed)
