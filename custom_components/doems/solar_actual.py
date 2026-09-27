"""Native completed-quarter Solar actual measurement for DOEMS validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.util import dt as dt_util

from .const import MIN_VALID_COVERAGE, QUARTER_MINUTES
from .energy_sources import normalize_power_w
from .solar_foundation import SolarFoundationManager
from .solar_forecast import SolarForecastManager


@dataclass(slots=True)
class SolarQuarterResult:
    """One completed native Solar quarter paired with its start-locked forecast."""

    start: datetime
    end: datetime
    energy_kwh: float | None
    coverage: float
    measurement_valid: bool
    source_entity: str | None
    forecast_kwh: float | None
    forecast_captured_at: datetime | None
    forecast_locked_at_start: bool
    forecast_error_kwh: float | None
    forecast_absolute_error_kwh: float | None
    forecast_error_percent: float | None

    @property
    def status(self) -> str:
        if not self.measurement_valid:
            return "measurement_invalid"
        if not self.forecast_locked_at_start or self.forecast_kwh is None:
            return "forecast_unavailable"
        return "ok"


def _forecast_error_metrics(
    actual_kwh: float | None,
    forecast_kwh: float | None,
) -> tuple[float | None, float | None, float | None]:
    """Return forecast-minus-actual error, absolute error and percent error."""
    if actual_kwh is None or forecast_kwh is None:
        return None, None, None
    error = round(forecast_kwh - actual_kwh, 6)
    absolute = round(abs(error), 6)
    percent = round(error / actual_kwh * 100.0, 1) if actual_kwh > 0 else None
    return error, absolute, percent


class SolarActualQuarterManager:
    """Integrate configured total Solar power over completed native quarters."""

    def __init__(
        self,
        hass: HomeAssistant,
        foundation: SolarFoundationManager,
        forecast: SolarForecastManager,
    ) -> None:
        self.hass = hass
        self.foundation = foundation
        self.forecast = forecast
        self.last_quarter: SolarQuarterResult | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

        self._quarter_start: datetime | None = None
        self._last_sample_time: datetime | None = None
        self._last_power_w: float | None = None
        self._energy_ws = 0.0
        self._covered_seconds = 0.0

        self._locked_forecast_kwh: float | None = None
        self._forecast_captured_at: datetime | None = None
        self._forecast_locked_at_start = False

    @property
    def source_entity(self) -> str | None:
        value = self.foundation.snapshot.get("total_actual_power_entity")
        return str(value) if value else None

    @property
    def enabled(self) -> bool:
        return self.foundation.status == "ready" and self.source_entity is not None

    @property
    def current_power_w(self) -> float | None:
        entity_id = self.source_entity
        state: State | None = self.hass.states.get(entity_id) if entity_id else None
        if state is None:
            return None
        return normalize_power_w(
            state.state,
            state.attributes.get("unit_of_measurement"),
            allow_negative=False,
        )

    async def async_setup(self) -> None:
        """Start actual-power integration and native quarter-boundary handling."""
        now = dt_util.utcnow()
        self._start_new_quarter(now, lock_forecast=False)
        self._last_power_w = self.current_power_w
        self._last_sample_time = now

        if self.source_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    [self.source_entity],
                    self._async_source_changed,
                )
            )
        self._unsubs.append(
            async_track_time_change(
                self.hass,
                self._async_quarter_boundary,
                minute=[0, 15, 30, 45],
                second=0,
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
    def _async_source_changed(self, event: Event[EventStateChangedData]) -> None:
        """Integrate the previous total Solar power until the source change."""
        now = dt_util.utcnow()
        self._integrate_until(now)
        self._last_power_w = self.current_power_w
        self._last_sample_time = now

    async def _async_quarter_boundary(self, now: datetime) -> None:
        now_utc = dt_util.as_utc(now)
        await self._advance_through_elapsed_boundaries(now_utc)
        self._notify()

    async def _advance_through_elapsed_boundaries(self, now_utc: datetime) -> None:
        if self._quarter_start is None:
            return
        now_utc = dt_util.as_utc(now_utc)
        while self._quarter_start + timedelta(minutes=QUARTER_MINUTES) <= now_utc:
            boundary_utc = self._quarter_start + timedelta(minutes=QUARTER_MINUTES)
            self._integrate_until(boundary_utc)
            self._finalize_quarter(boundary_utc)
            natural_boundary = abs((now_utc - boundary_utc).total_seconds()) <= 5.0
            self._start_new_quarter(boundary_utc, lock_forecast=natural_boundary)
            self._last_power_w = self.current_power_w
            self._last_sample_time = boundary_utc

    def _start_new_quarter(self, now_utc: datetime, *, lock_forecast: bool) -> None:
        local = dt_util.as_local(now_utc)
        minute = (local.minute // QUARTER_MINUTES) * QUARTER_MINUTES
        local_start = local.replace(minute=minute, second=0, microsecond=0)
        self._quarter_start = dt_util.as_utc(local_start)
        self._energy_ws = 0.0
        self._covered_seconds = 0.0
        self._last_sample_time = dt_util.as_utc(now_utc)
        self._capture_forecast(self._quarter_start, locked_at_start=lock_forecast)

    def _capture_forecast(self, start_utc: datetime, *, locked_at_start: bool) -> None:
        point = self.forecast.forecast_point_for_start(start_utc)
        self._locked_forecast_kwh = point.total_kwh if point is not None else None
        self._forecast_captured_at = dt_util.utcnow() if point is not None else None
        self._forecast_locked_at_start = bool(locked_at_start and point is not None)

    def _integrate_until(self, now_utc: datetime) -> None:
        now_utc = dt_util.as_utc(now_utc)
        if self._last_sample_time is None:
            self._last_sample_time = now_utc
            return
        seconds = max(0.0, (now_utc - self._last_sample_time).total_seconds())
        if self._last_power_w is not None and seconds > 0:
            self._energy_ws += self._last_power_w * seconds
            self._covered_seconds += seconds
        self._last_sample_time = now_utc

    def _finalize_quarter(self, end_utc: datetime) -> None:
        if self._quarter_start is None:
            return
        duration = max(1.0, (end_utc - self._quarter_start).total_seconds())
        coverage = min(1.0, self._covered_seconds / duration)
        measurement_valid = coverage >= MIN_VALID_COVERAGE
        energy_kwh = self._energy_ws / 3_600_000 if measurement_valid else None
        actual = round(energy_kwh, 6) if energy_kwh is not None else None
        forecast = (
            round(self._locked_forecast_kwh, 6)
            if self._locked_forecast_kwh is not None
            else None
        )
        comparable_forecast = forecast if self._forecast_locked_at_start else None
        error, absolute, percent = _forecast_error_metrics(actual, comparable_forecast)
        self.last_quarter = SolarQuarterResult(
            start=self._quarter_start,
            end=end_utc,
            energy_kwh=actual,
            coverage=round(coverage, 4),
            measurement_valid=measurement_valid,
            source_entity=self.source_entity,
            forecast_kwh=forecast,
            forecast_captured_at=self._forecast_captured_at,
            forecast_locked_at_start=self._forecast_locked_at_start,
            forecast_error_kwh=error,
            forecast_absolute_error_kwh=absolute,
            forecast_error_percent=percent,
        )
