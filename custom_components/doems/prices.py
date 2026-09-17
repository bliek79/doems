"""DOEMS Prices P4.1 runtime."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any, Callable

from aiohttp import ClientError
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
    CONF_PRICE_RESOLUTION_PREFERENCE,
    CONF_PRICES_ENABLED,
    CONF_TARIFF_PROFILE_ID,
    CONF_TARIFF_SUPPLIER,
    CONF_TARIFF_VALID_FROM,
    CONF_VAT_PERCENT,
    FORECAST_HORIZON_HOURS,
    FORECAST_SLOTS,
    PRICE_BUFFER_HOURS,
    PRICE_BUFFER_SLOT_COUNT,
    PRICE_RESOLUTION_AUTO,
    PRICES_PROVIDER,
    PRICES_REFRESH_MINUTES,
    PRICES_SOURCE_ATTRIBUTION,
    PRICES_STALE_HOURS,
    QUARTER_MINUTES,
)
from .prices_model import (
    PricePoint,
    build_price_index,
    ceil_quarter,
    expected_quarter_starts,
    find_current_known_point,
    floor_quarter,
    select_exact_window,
    utc,
)

_LOGGER = logging.getLogger(__name__)
PRICES_URL = "https://stroomvoorspeller.nl/data/prices.json"
FORECAST_URL = "https://stroomvoorspeller.nl/data/forecast.json"
REFRESH_INTERVAL = timedelta(minutes=PRICES_REFRESH_MINUTES)
SOURCE_STALE_AFTER = timedelta(hours=PRICES_STALE_HOURS)
PUBLIC_PRICE_ENTITY_IDS = (
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
    """Fetch and normalize prices without physical execution authority."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._indexed: dict[datetime, PricePoint] = {}
        self.points: list[PricePoint] = []
        self.missing_public_starts: list[datetime] = []
        self.buffer_points: list[PricePoint] = []
        self.buffer_missing_starts: list[datetime] = []
        self.buffer_start: datetime | None = None
        self.buffer_end: datetime | None = None
        self.timeline_start: datetime | None = None
        self.timeline_end: datetime | None = None
        self.last_attempt: datetime | None = None
        self.last_successful_update: datetime | None = None
        self.last_error: str | None = None
        self.source_generated_at: str | None = None
        self.forecast_generated_at: str | None = None
        self.provider_has_pt15m = False
        self.pt15m_slots = 0
        self.pt15m_first_time: datetime | None = None
        self.pt15m_last_time: datetime | None = None
        self.known_slots = 0
        self.forecast_slots = 0
        self.duplicate_slots = 0

    @property
    def enabled(self) -> bool:
        return bool(self.entry.options.get(CONF_PRICES_ENABLED, False))

    @property
    def gas_enabled(self) -> bool:
        return bool(self.entry.options.get(CONF_GAS_PRICES_ENABLED, False))

    @property
    def resolution_preference(self) -> str:
        return str(self.entry.options.get(CONF_PRICE_RESOLUTION_PREFERENCE, PRICE_RESOLUTION_AUTO))

    def _num(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.entry.options.get(key, default))
        except (TypeError, ValueError):
            return default

    @property
    def tariff_snapshot(self) -> dict[str, Any]:
        return {
            "profile_id": str(self.entry.options.get(CONF_TARIFF_PROFILE_ID, "unconfigured")),
            "supplier": str(self.entry.options.get(CONF_TARIFF_SUPPLIER, "")),
            "valid_from": self.entry.options.get(CONF_TARIFF_VALID_FROM),
            "vat_percent": self._num(CONF_VAT_PERCENT, 21.0),
            "electricity_import_supplier_incl_vat": self._num(CONF_ELECTRICITY_IMPORT_SUPPLIER),
            "electricity_import_tax_incl_vat": self._num(CONF_ELECTRICITY_IMPORT_TAX),
            "electricity_export_supplier_incl_vat": self._num(CONF_ELECTRICITY_EXPORT_SUPPLIER),
            "electricity_export_tax_incl_vat": self._num(CONF_ELECTRICITY_EXPORT_TAX),
            "electricity_fixed_supply_per_day": self._num(CONF_ELECTRICITY_FIXED_SUPPLY_PER_DAY),
            "electricity_grid_per_day": self._num(CONF_ELECTRICITY_GRID_PER_DAY),
            "electricity_tax_credit_per_day": self._num(CONF_ELECTRICITY_TAX_CREDIT_PER_DAY),
            "price_resolution_preference": self.resolution_preference,
            "electricity_provider": PRICES_PROVIDER,
            "gas_prices_enabled": self.gas_enabled,
            "gas_market_entity": self.entry.options.get(CONF_GAS_MARKET_ENTITY) if self.gas_enabled else None,
            "gas_supplier_incl_vat": self._num(CONF_GAS_SUPPLIER) if self.gas_enabled else None,
            "gas_tax_incl_vat": self._num(CONF_GAS_TAX) if self.gas_enabled else None,
            "gas_fixed_supply_per_day": self._num(CONF_GAS_FIXED_SUPPLY_PER_DAY) if self.gas_enabled else None,
            "gas_grid_per_day": self._num(CONF_GAS_GRID_PER_DAY) if self.gas_enabled else None,
            "fixed_costs_affect_marginal_slot_ranking": False,
            "immutable_history_rule": True,
            "future_profile_changes_do_not_reprice_history": True,
        }

    @property
    def freshness(self) -> str:
        if self.last_successful_update is None:
            return "not_loaded"
        return "stale" if dt_util.utcnow() - self.last_successful_update > SOURCE_STALE_AFTER else "fresh"

    @property
    def age_minutes(self) -> float | None:
        if self.last_successful_update is None:
            return None
        return round(max(0.0, (dt_util.utcnow() - self.last_successful_update).total_seconds()) / 60.0, 1)

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.last_successful_update is None:
            return "error" if self.last_error else "not_loaded"
        if self.last_error or self.freshness == "stale":
            return "stale"
        return "ok" if len(self.points) == FORECAST_SLOTS else "partial"

    @property
    def gas_market_entity(self) -> str | None:
        if not self.gas_enabled:
            return None
        value = self.entry.options.get(CONF_GAS_MARKET_ENTITY)
        return str(value) if value else None

    @property
    def gas_market_price(self) -> float | None:
        entity_id = self.gas_market_entity
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
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
    def current_point(self) -> PricePoint | None:
        return find_current_known_point(self._indexed, now=dt_util.utcnow()) if self._indexed else None

    async def async_setup(self) -> None:
        if not self.enabled:
            return
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
        for entity_id in PUBLIC_PRICE_ENTITY_IDS:
            self.hass.states.async_remove(entity_id)

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
        self._publish_states()
        self._notify()

    async def _fetch_json(self, url: str) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        async with session.get(url, timeout=20) as response:
            response.raise_for_status()
            payload = await response.json()
            if not isinstance(payload, dict):
                raise ValueError("provider_payload_not_object")
            return payload

    async def async_refresh(self) -> None:
        if not self.enabled:
            return
        self.last_attempt = dt_util.utcnow()
        try:
            prices_payload, forecast_payload = await asyncio.gather(
                self._fetch_json(PRICES_URL),
                self._fetch_json(FORECAST_URL),
            )
            indexed, diagnostics = build_price_index(
                prices_payload,
                forecast_payload,
                resolution_preference=self.resolution_preference,
                vat_percent=self._num(CONF_VAT_PERCENT, 21.0),
                import_supplier_incl_vat=self._num(CONF_ELECTRICITY_IMPORT_SUPPLIER),
                import_tax_incl_vat=self._num(CONF_ELECTRICITY_IMPORT_TAX),
                export_supplier_incl_vat=self._num(CONF_ELECTRICITY_EXPORT_SUPPLIER),
                export_tax_incl_vat=self._num(CONF_ELECTRICITY_EXPORT_TAX),
            )
            if not indexed:
                raise ValueError("provider_timeline_empty")
            self._indexed = indexed
            self.provider_has_pt15m = bool(diagnostics["provider_has_pt15m"])
            self.pt15m_slots = int(diagnostics["pt15m_slots"])
            self.pt15m_first_time = diagnostics["pt15m_first_time"]
            self.pt15m_last_time = diagnostics["pt15m_last_time"]
            self.known_slots = int(diagnostics["known_slots"])
            self.forecast_slots = int(diagnostics["forecast_slots"])
            self.duplicate_slots = int(diagnostics["duplicate_slots"])
            self.source_generated_at = prices_payload.get("generated_at") or prices_payload.get("generated")
            self.forecast_generated_at = forecast_payload.get("generated_at") or forecast_payload.get("generated")
            self.last_successful_update = dt_util.utcnow()
            self.last_error = None
            self._rebuild_views(self.last_successful_update)
        except (ClientError, asyncio.TimeoutError, ValueError, TypeError, KeyError) as err:
            self.last_error = f"{type(err).__name__}: {err}"
            _LOGGER.warning("DOEMS Prices P4.1 refresh failed: %s", self.last_error)
            if self._indexed:
                self._rebuild_views(dt_util.utcnow())
        self._publish_states()
        self._notify()

    def _rebuild_views(self, reference: datetime) -> None:
        buffer_start = floor_quarter(reference)
        self.buffer_points, self.buffer_missing_starts = select_exact_window(
            self._indexed,
            start=buffer_start,
            slot_count=PRICE_BUFFER_SLOT_COUNT,
        )
        self.buffer_start = utc(buffer_start)
        self.buffer_end = self.buffer_start + timedelta(hours=PRICE_BUFFER_HOURS)

        timeline_start = ceil_quarter(reference)
        self.points, self.missing_public_starts = select_exact_window(
            self._indexed,
            start=timeline_start,
            slot_count=FORECAST_SLOTS,
        )
        self.timeline_start = utc(timeline_start)
        self.timeline_end = self.timeline_start + timedelta(hours=FORECAST_HORIZON_HOURS)

    def timeline_points(self) -> list[dict[str, Any]]:
        """Return exactly 288 positional records; missing data remains explicit nulls."""
        if self.timeline_start is None:
            return []
        by_start = {point.start: point for point in self.points}
        result: list[dict[str, Any]] = []
        for stamp in expected_quarter_starts(self.timeline_start, FORECAST_SLOTS):
            point = by_start.get(stamp)
            if point is None:
                result.append(
                    {
                        "time": stamp.isoformat(),
                        "market_ex_vat": None,
                        "market_incl_vat": None,
                        "import_all_in": None,
                        "export_all_in": None,
                        "kind": "missing",
                        "source_resolution_minutes": None,
                        "lower_ex_vat": None,
                        "upper_ex_vat": None,
                        "forecast_generated_at": None,
                        "uncertainty_pct": None,
                        "regime": None,
                        "valid": False,
                    }
                )
            else:
                item = point.as_dict()
                item["valid"] = True
                result.append(item)
        return result

    @staticmethod
    def _state(value: float | int | str | None) -> float | int | str:
        return "unknown" if value is None else value

    def _publish_states(self) -> None:
        """Publish stable provider-neutral DOEMS Prices states."""
        if not self.enabled:
            return
        common = self.common_attributes
        point = self.current_point
        point_attrs = point.as_dict() if point else {}
        self.hass.states.async_set("sensor.doems_prices_status", self.status, common)
        for kind, value, basis in (
            ("market", point.market_incl_vat if point else None, "market_incl_vat"),
            ("import", point.import_all_in if point else None, "marginal_import_all_in"),
            ("export", point.export_all_in if point else None, "marginal_export_all_in"),
        ):
            self.hass.states.async_set(
                f"sensor.doems_prices_{kind}_current",
                self._state(value),
                {
                    **common,
                    **point_attrs,
                    "unit_of_measurement": "EUR/kWh",
                    "price_basis": basis,
                    "current_semantics": "actual_current_quarter_known_only",
                    "fixed_daily_costs_included": False,
                },
            )
        self.hass.states.async_set(
            "sensor.doems_prices_timeline",
            len(self.points),
            {
                **common,
                "slot_count": FORECAST_SLOTS,
                "point_count": FORECAST_SLOTS if self.timeline_start else 0,
                "point_format": "dict:v1",
                "point_fields": [
                    "time",
                    "market_ex_vat",
                    "market_incl_vat",
                    "import_all_in",
                    "export_all_in",
                    "kind",
                    "source_resolution_minutes",
                    "lower_ex_vat",
                    "upper_ex_vat",
                    "forecast_generated_at",
                    "uncertainty_pct",
                    "regime",
                    "valid",
                ],
                "import_series_field": "import_all_in",
                "export_series_field": "export_all_in",
                "known_vs_forecast_field": "kind",
                "missing_semantics": "explicit_null_record_keeps_slot_position",
                "recorder_recommendation": "exclude timeline points attribute from Recorder",
                "points": self.timeline_points(),
            },
        )
        tariff = self.tariff_snapshot
        self.hass.states.async_set("sensor.doems_prices_tariff_profile", tariff["profile_id"], tariff)
        if self.gas_enabled:
            gas_common = {
                "unit_of_measurement": "EUR/m3",
                "source_entity": self.gas_market_entity,
                "tariff_profile_id": tariff["profile_id"],
                "tariff_valid_from": tariff["valid_from"],
                "physical_execution_authority": False,
            }
            self.hass.states.async_set(
                "sensor.doems_prices_gas_market",
                self._state(self.gas_market_price),
                {**gas_common, "price_basis": "external_gas_market"},
            )
            self.hass.states.async_set(
                "sensor.doems_prices_gas_all_in",
                self._state(self.gas_all_in_price),
                {
                    **gas_common,
                    "price_basis": "gas_market_plus_variable_tariff",
                    "market_price_incl_vat": self.gas_market_price,
                    "variable_addon_incl_vat": round(self.gas_variable_addon, 6),
                    "gas_fixed_supply_per_day": tariff["gas_fixed_supply_per_day"],
                    "gas_grid_per_day": tariff["gas_grid_per_day"],
                    "fixed_daily_costs_included": False,
                },
            )
        else:
            self.hass.states.async_remove("sensor.doems_prices_gas_market")
            self.hass.states.async_remove("sensor.doems_prices_gas_all_in")

    @property
    def common_attributes(self) -> dict[str, Any]:
        point = self.current_point
        return {
            "status": self.status,
            "freshness": self.freshness,
            "provider": PRICES_PROVIDER,
            "attribution": PRICES_SOURCE_ATTRIBUTION,
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
            "last_successful_update": self.last_successful_update.isoformat() if self.last_successful_update else None,
            "age_minutes": self.age_minutes,
            "prices_generated_at": self.source_generated_at,
            "forecast_generated_at": self.forecast_generated_at,
            "price_resolution_preference": self.resolution_preference,
            "provider_has_pt15m": self.provider_has_pt15m,
            "pt15m_slots": self.pt15m_slots,
            "pt15m_first_time": self.pt15m_first_time.isoformat() if self.pt15m_first_time else None,
            "pt15m_last_time": self.pt15m_last_time.isoformat() if self.pt15m_last_time else None,
            "known_slots": self.known_slots,
            "forecast_slots": self.forecast_slots,
            "duplicate_slots": self.duplicate_slots,
            "current_price_source": point.kind if point else "missing",
            "resolution_minutes": QUARTER_MINUTES,
            "horizon_hours": FORECAST_HORIZON_HOURS,
            "expected_slots": FORECAST_SLOTS,
            "valid_slots": len(self.points),
            "missing_slots": len(self.missing_public_starts),
            "timeline_start": self.timeline_start.isoformat() if self.timeline_start else None,
            "timeline_end": self.timeline_end.isoformat() if self.timeline_end else None,
            "price_buffer_hours": PRICE_BUFFER_HOURS,
            "price_buffer_expected_slots": PRICE_BUFFER_SLOT_COUNT,
            "price_buffer_valid_slots": len(self.buffer_points),
            "price_buffer_missing_slots": len(self.buffer_missing_starts),
            "price_buffer_start": self.buffer_start.isoformat() if self.buffer_start else None,
            "price_buffer_end": self.buffer_end.isoformat() if self.buffer_end else None,
            "tariff_profile_id": self.tariff_snapshot["profile_id"],
            "error": self.last_error,
            "physical_execution_authority": False,
        }
