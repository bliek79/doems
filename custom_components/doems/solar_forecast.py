"""Open-Meteo Solar P3.1 runtime for the generic DOEMS Solar Foundation."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import logging
import math
from typing import Any, Callable
from zoneinfo import ZoneInfo

from aiohttp import ClientError

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import FORECAST_SLOTS, QUARTER_MINUTES
from .solar_foundation import SolarFoundationManager
from .solar_forecast_model import (
    SOLAR_FORECAST_MODEL,
    SOLAR_FORECAST_SLOTS,
    SOLAR_HORIZON_HOURS,
    SOLAR_PERFORMANCE_FACTOR,
    SOLAR_RESOLUTION_MINUTES,
    SolarForecastPoint,
    backward_average_slot_start,
    build_forecast_timeline,
    canonical_to_open_meteo_azimuth,
    next_complete_slot,
)

_LOGGER = logging.getLogger(__name__)

OPEN_METEO_SOLAR_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_SOLAR_TIMEZONE = "UTC"
OPEN_METEO_SOLAR_PROVIDER_MODEL = "best_match"
SOLAR_BUFFER_SLOTS = 4
SOLAR_REQUEST_EXTRA_SLOTS = 7
SOLAR_REFRESH_MINUTE = 0
SOLAR_REFRESH_SECOND = 20
SOLAR_RETRY_DELAYS_SECONDS = (0, 5, 15)
SOLAR_STALE_MINUTES = 90
SOLAR_EXPIRED_MINUTES = 180


class SolarForecastManager:
    """Fetch one GTI series per configured array and publish one 1..N Solar timeline."""

    def __init__(self, hass: HomeAssistant, foundation: SolarFoundationManager) -> None:
        self.hass = hass
        self.foundation = foundation
        self._source_points: list[SolarForecastPoint] = []
        self.last_attempt: datetime | None = None
        self.last_successful_update: datetime | None = None
        self.last_error: str | None = None
        self.source_generation_time_ms: dict[str, float | None] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

    @property
    def foundation_snapshot(self) -> dict[str, Any]:
        return self.foundation.snapshot

    @property
    def enabled(self) -> bool:
        snapshot = self.foundation_snapshot
        return bool(snapshot.get("enabled")) and snapshot.get("status") == "ready"

    @property
    def points(self) -> list[SolarForecastPoint]:
        """Return exactly the rolling native 72-hour window when available."""
        if not self._source_points:
            return []
        cutoff = dt_util.as_utc(next_complete_slot(dt_util.as_local(dt_util.utcnow())))
        return [point for point in self._source_points if point.start >= cutoff][:SOLAR_FORECAST_SLOTS]

    @property
    def source_point_count(self) -> int:
        return len(self._source_points)

    @property
    def age_minutes(self) -> float | None:
        if self.last_successful_update is None:
            return None
        return round(
            max(0.0, (dt_util.utcnow() - self.last_successful_update).total_seconds()) / 60.0,
            1,
        )

    @property
    def source_status(self) -> str:
        if not self.enabled:
            return "foundation_not_ready"
        if self.last_successful_update is None:
            return "error" if self.last_error else "not_loaded"
        if (self.age_minutes or 0.0) >= SOLAR_EXPIRED_MINUTES or not self.points:
            return "expired"
        if self.last_error or (self.age_minutes or 0.0) >= SOLAR_STALE_MINUTES or len(self.points) < SOLAR_FORECAST_SLOTS:
            return "stale"
        return "ok"

    async def async_setup(self) -> None:
        """Start the provider runtime only for a ready Solar Foundation."""
        self.foundation.forecast_runtime_active = self.enabled
        if not self.enabled:
            self._notify()
            return
        await self.async_refresh()
        self._unsubs.append(
            async_track_time_change(
                self.hass,
                self._async_hourly_refresh,
                minute=SOLAR_REFRESH_MINUTE,
                second=SOLAR_REFRESH_SECOND,
            )
        )

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self.foundation.forecast_runtime_active = False

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

    async def _async_hourly_refresh(self, _now: datetime) -> None:
        await self.async_refresh()

    async def async_refresh(self) -> None:
        """Refresh all configured arrays; retain the last valid timeline on failure."""
        if not self.enabled:
            self.last_error = "foundation_not_ready"
            self._notify()
            return

        last_error: Exception | None = None
        for attempt, delay in enumerate(SOLAR_RETRY_DELAYS_SECONDS, start=1):
            if delay:
                await asyncio.sleep(delay)
            self.last_attempt = dt_util.utcnow()
            try:
                arrays = self._arrays()
                payloads = await asyncio.gather(
                    *(self._fetch_array(array) for array in arrays)
                )
                self._apply_payloads(arrays, payloads)
                self.last_successful_update = dt_util.utcnow()
                self.last_error = None
                self._notify()
                return
            except (ClientError, asyncio.TimeoutError, ValueError, TypeError, KeyError) as err:
                last_error = err
                _LOGGER.warning(
                    "DOEMS P3.1 Open-Meteo Solar refresh attempt %s/%s failed: %s",
                    attempt,
                    len(SOLAR_RETRY_DELAYS_SECONDS),
                    err,
                )

        self.last_error = (
            f"{type(last_error).__name__}: {last_error}"
            if last_error is not None
            else "unknown_error"
        )
        self._notify()

    def _arrays(self) -> list[dict[str, Any]]:
        arrays = self.foundation_snapshot.get("arrays")
        if not isinstance(arrays, list) or not arrays:
            raise ValueError("array_missing")
        return [dict(item) for item in arrays if isinstance(item, dict)]

    def _request_params(self, array: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.foundation_snapshot
        latitude = snapshot.get("latitude")
        longitude = snapshot.get("longitude")
        if latitude is None or longitude is None:
            raise ValueError("foundation_location_missing")
        return {
            "latitude": float(latitude),
            "longitude": float(longitude),
            "minutely_15": "global_tilted_irradiance",
            "forecast_minutely_15": SOLAR_FORECAST_SLOTS + SOLAR_REQUEST_EXTRA_SLOTS,
            "tilt": float(array["tilt_deg"]),
            "azimuth": canonical_to_open_meteo_azimuth(float(array["azimuth_deg"])),
            "models": OPEN_METEO_SOLAR_PROVIDER_MODEL,
            "timezone": OPEN_METEO_SOLAR_TIMEZONE,
        }

    async def _fetch_array(self, array: dict[str, Any]) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        async with session.get(
            OPEN_METEO_SOLAR_ENDPOINT,
            params=self._request_params(array),
            timeout=20,
        ) as response:
            response.raise_for_status()
            return await response.json()

    def _apply_payloads(
        self,
        arrays: list[dict[str, Any]],
        payloads: list[dict[str, Any]],
    ) -> None:
        if len(arrays) != len(payloads):
            raise ValueError("array_payload_count_mismatch")

        cutoff_utc = dt_util.as_utc(next_complete_slot(dt_util.as_local(dt_util.utcnow())))
        irradiance_by_array: dict[str, dict[datetime, float]] = {}
        generation_times: dict[str, float | None] = {}
        ordered_starts: list[datetime] | None = None

        for array, payload in zip(arrays, payloads, strict=True):
            array_id = str(array.get("array_id") or "")
            if not array_id:
                raise ValueError("array_id_missing")
            normalized = self._normalize_irradiance(payload, cutoff_utc)
            starts = sorted(normalized)
            if ordered_starts is None:
                ordered_starts = starts
            elif starts != ordered_starts:
                raise ValueError("Open-Meteo array timelines do not align")
            irradiance_by_array[array_id] = normalized
            generation_times[array_id] = self._as_float(payload.get("generationtime_ms"))

        if ordered_starts is None or len(ordered_starts) < SOLAR_FORECAST_SLOTS:
            count = len(ordered_starts or [])
            raise ValueError(
                f"Open-Meteo solar produced {count} aligned slots; expected at least {SOLAR_FORECAST_SLOTS}"
            )

        self._source_points = build_forecast_timeline(
            self.foundation_snapshot,
            starts=ordered_starts,
            irradiance_by_array=irradiance_by_array,
            performance_factor=SOLAR_PERFORMANCE_FACTOR,
        )
        self.source_generation_time_ms = generation_times

    @staticmethod
    def _normalize_irradiance(
        payload: dict[str, Any],
        cutoff_utc: datetime,
    ) -> dict[datetime, float]:
        minutely = payload.get("minutely_15")
        if not isinstance(minutely, dict):
            raise ValueError("Open-Meteo response missing minutely_15")
        times = minutely.get("time")
        values = minutely.get("global_tilted_irradiance")
        if not isinstance(times, list) or not isinstance(values, list):
            raise ValueError("Open-Meteo response missing solar time axis or irradiance")

        timezone = ZoneInfo(str(payload.get("timezone") or OPEN_METEO_SOLAR_TIMEZONE))
        result: dict[datetime, float] = {}
        for index, raw_time in enumerate(times):
            if index >= len(values) or not isinstance(raw_time, str):
                continue
            source_time = datetime.fromisoformat(raw_time)
            if source_time.tzinfo is None:
                source_time = source_time.replace(tzinfo=timezone)
            slot_start_utc = backward_average_slot_start(
                source_time.astimezone(dt_util.UTC), SOLAR_RESOLUTION_MINUTES
            )
            if slot_start_utc < cutoff_utc:
                continue
            value = values[index]
            try:
                if value is None:
                    raise ValueError
                irradiance = float(value)
                if not math.isfinite(irradiance):
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError(f"Invalid irradiance at {raw_time}") from None
            result[slot_start_utc] = max(0.0, irradiance)
            if len(result) >= SOLAR_FORECAST_SLOTS + SOLAR_BUFFER_SLOTS:
                break
        return result

    def next_quarter_point(self) -> SolarForecastPoint | None:
        points = self.points
        return points[0] if points else None

    def energy_for_local_date(self, target: date) -> float | None:
        points = self.points
        if not points:
            return None
        return round(
            sum(
                point.total_kwh
                for point in points
                if dt_util.as_local(point.start).date() == target
            ),
            3,
        )

    def array_energy_for_local_date(self, target: date) -> dict[str, float]:
        points = self.points
        arrays = self._arrays()
        totals = {str(array["array_id"]): 0.0 for array in arrays}
        for point in points:
            if dt_util.as_local(point.start).date() != target:
                continue
            for index, array_id in enumerate(point.array_ids):
                totals[array_id] += point.array_kwh[index]
        return {array_id: round(value, 3) for array_id, value in totals.items()}

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    @property
    def contract(self) -> dict[str, Any]:
        snapshot = self.foundation_snapshot
        arrays = self._arrays() if self.enabled else []
        return {
            "provider": "open_meteo",
            "provider_model": OPEN_METEO_SOLAR_PROVIDER_MODEL,
            "model": SOLAR_FORECAST_MODEL,
            "source_variable": "global_tilted_irradiance",
            "source_timezone": OPEN_METEO_SOLAR_TIMEZONE,
            "resolution_minutes": SOLAR_RESOLUTION_MINUTES,
            "horizon_hours": SOLAR_HORIZON_HOURS,
            "slot_count": SOLAR_FORECAST_SLOTS,
            "performance_factor": SOLAR_PERFORMANCE_FACTOR,
            "location_source": snapshot.get("location_source"),
            "latitude": snapshot.get("latitude"),
            "longitude": snapshot.get("longitude"),
            "topology_signature": snapshot.get("topology_signature"),
            "array_ids": [str(array.get("array_id")) for array in arrays],
            "array_names": [str(array.get("name")) for array in arrays],
            "canonical_azimuth_deg": [array.get("azimuth_deg") for array in arrays],
            "open_meteo_azimuth_deg": [
                canonical_to_open_meteo_azimuth(float(array["azimuth_deg"]))
                for array in arrays
            ],
            "group_ac_limit_semantics": "cap_group_sum_then_scale_member_arrays_proportionally",
            "native_contract_matches_global": (
                SOLAR_RESOLUTION_MINUTES == QUARTER_MINUTES
                and SOLAR_FORECAST_SLOTS == FORECAST_SLOTS
            ),
            "physical_execution_authority": False,
        }
