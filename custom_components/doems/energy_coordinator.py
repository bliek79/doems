"""Quarter-hour history coordinator for DOEMS Energy Forecast."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CANONICAL_HOME_POWER_ENTITY,
    CONF_BATTERY_CHARGE_POWER_ENTITY,
    CONF_BATTERY_DISCHARGE_POWER_ENTITY,
    CONF_BATTERY_PRESENT,
    CONF_ENERGY_SOURCE_MODE,
    CONF_ENERGY_START_PROFILE,
    CONF_GRID_NET_POWER_ENTITY,
    CONF_GRID_SIGN_CONVENTION,
    CONF_HOME_POWER_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    ENERGY_SOURCE_BALANCE,
    ENERGY_SOURCE_DIRECT,
    ENERGY_STORE_SCHEMA_VERSION,
    GRID_SIGN_POSITIVE_IMPORT,
    MAX_HISTORY_DAYS,
    MIN_VALID_COVERAGE,
    PROFILE_AWAY,
    PROFILE_LEARNING_OPTIONS,
    PROFILE_MIXED,
    PROFILE_NORMAL,
    PROFILE_OPTIONS,
    PROFILE_UNCLASSIFIED,
    QUARTER_MINUTES,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .energy_forecast import EnergyBaselineForecast
from .energy_sources import (
    configured_source_entities,
    home_power_from_balance_w,
    normalize_grid_net_w,
    normalize_power_w,
    source_signature,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class QuarterResult:
    """Completed native quarter and learning eligibility."""

    start: datetime
    end: datetime
    energy_kwh: float | None
    coverage: float
    profile: str
    measurement_valid: bool
    learning_valid: bool
    learning_blocker: str | None

    @property
    def valid(self) -> bool:
        return self.learning_valid


class DOEMSEnergyCoordinator:
    """Collect clean DOEMS Home Power history at native 15-minute resolution."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.profile = PROFILE_UNCLASSIFIED
        self.previous_profile: str | None = None
        self.profile_changed_at: str | None = None
        self.profile_change_source = "initial_default"
        self.records: list[dict[str, Any]] = []
        self.last_quarter: QuarterResult | None = None
        self.history_reset_reason: str | None = None
        self.listeners: list[callback] = []

        self._source_signature = source_signature(dict(entry.options))
        self._quarter_start: datetime | None = None
        self._last_sample_time: datetime | None = None
        self._last_power_w: float | None = None
        self._energy_ws = 0.0
        self._covered_seconds = 0.0
        self._quarter_profile = PROFILE_UNCLASSIFIED
        self._profile_changed_in_quarter = False
        self._unsubs: list[Any] = []

    @property
    def source_entity(self) -> str:
        """Return the public canonical Home Power entity ID."""
        return CANONICAL_HOME_POWER_ENTITY

    @property
    def source_entities(self) -> list[str]:
        """Return physical Home Assistant source entity IDs."""
        return configured_source_entities(dict(self.entry.options))

    @property
    def source_mode(self) -> str | None:
        return self.entry.options.get(CONF_ENERGY_SOURCE_MODE)

    async def async_setup(self) -> None:
        """Load clean storage and start source/boundary listeners."""
        stored = await self.store.async_load() or {}
        stored_signature = stored.get("source_signature")
        if (
            stored.get("energy_store_schema_version") == ENERGY_STORE_SCHEMA_VERSION
            and stored_signature == self._source_signature
        ):
            profile = stored.get("profile", PROFILE_UNCLASSIFIED)
            self.profile = profile if profile in PROFILE_OPTIONS else PROFILE_UNCLASSIFIED
            self.previous_profile = stored.get("previous_profile")
            self.profile_changed_at = stored.get("profile_changed_at")
            self.profile_change_source = stored.get("profile_change_source", "storage")
            records = stored.get("records", [])
            self.records = list(records) if isinstance(records, list) else []
        else:
            start_profile = self.entry.options.get(CONF_ENERGY_START_PROFILE, PROFILE_NORMAL)
            self.profile = start_profile if start_profile in PROFILE_LEARNING_OPTIONS else PROFILE_NORMAL
            if stored_signature and stored_signature != self._source_signature:
                self.history_reset_reason = "source_signature_changed"
            elif stored:
                self.history_reset_reason = "storage_contract_changed"
            else:
                self.history_reset_reason = "clean_start"

        self._prune_records()
        now = dt_util.utcnow()
        self._start_new_quarter(now)
        self._last_power_w = self.current_home_power_w
        self._last_sample_time = now
        await self._async_save()

        entities = self.source_entities
        if entities:
            self._unsubs.append(
                async_track_state_change_event(self.hass, entities, self._async_source_changed)
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
        await self._async_save()

    def async_add_listener(self, listener: callback) -> callback:
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

    def _state_power_w(self, entity_id: str | None, *, allow_negative: bool) -> float | None:
        state: State | None = self.hass.states.get(entity_id) if entity_id else None
        if state is None:
            return None
        return normalize_power_w(
            state.state,
            state.attributes.get("unit_of_measurement"),
            allow_negative=allow_negative,
        )

    @property
    def current_home_power_w(self) -> float | None:
        """Return canonical current Home Power using the selected install contract."""
        options = self.entry.options
        mode = options.get(CONF_ENERGY_SOURCE_MODE)
        if mode == ENERGY_SOURCE_DIRECT:
            return self._state_power_w(options.get(CONF_HOME_POWER_ENTITY), allow_negative=False)
        if mode != ENERGY_SOURCE_BALANCE:
            return None

        grid_raw = self._state_power_w(options.get(CONF_GRID_NET_POWER_ENTITY), allow_negative=True)
        solar = self._state_power_w(options.get(CONF_SOLAR_POWER_ENTITY), allow_negative=False)
        if grid_raw is None or solar is None:
            return None
        try:
            grid_net = normalize_grid_net_w(
                grid_raw,
                options.get(CONF_GRID_SIGN_CONVENTION, GRID_SIGN_POSITIVE_IMPORT),
            )
        except ValueError:
            return None

        charge = 0.0
        discharge = 0.0
        if options.get(CONF_BATTERY_PRESENT):
            charge_value = self._state_power_w(
                options.get(CONF_BATTERY_CHARGE_POWER_ENTITY), allow_negative=False
            )
            discharge_value = self._state_power_w(
                options.get(CONF_BATTERY_DISCHARGE_POWER_ENTITY), allow_negative=False
            )
            if charge_value is None or discharge_value is None:
                return None
            charge = charge_value
            discharge = discharge_value

        return home_power_from_balance_w(
            grid_net_w=grid_net,
            solar_w=solar,
            battery_charge_w=charge,
            battery_discharge_w=discharge,
        )

    @property
    def source_available(self) -> bool:
        return self.current_home_power_w is not None

    @callback
    def _async_source_changed(self, event: Event[EventStateChangedData]) -> None:
        """Integrate the previous Home Power until the source change."""
        now = dt_util.utcnow()
        self._integrate_until(now)
        self._last_power_w = self.current_home_power_w
        self._last_sample_time = now

    async def _async_quarter_boundary(self, now: datetime) -> None:
        now_utc = dt_util.as_utc(now)
        await self._advance_through_elapsed_boundaries(now_utc)
        await self._async_save()
        self._notify()

    async def _advance_through_elapsed_boundaries(self, now_utc: datetime) -> None:
        if self._quarter_start is None:
            return
        now_utc = dt_util.as_utc(now_utc)
        while self._quarter_start + timedelta(minutes=QUARTER_MINUTES) <= now_utc:
            boundary_utc = self._quarter_start + timedelta(minutes=QUARTER_MINUTES)
            self._integrate_until(boundary_utc)
            await self._finalize_quarter(boundary_utc)
            self._start_new_quarter(boundary_utc)
            self._last_power_w = self.current_home_power_w
            self._last_sample_time = boundary_utc

    def _start_new_quarter(self, now_utc: datetime) -> None:
        local = dt_util.as_local(now_utc)
        minute = (local.minute // QUARTER_MINUTES) * QUARTER_MINUTES
        local_start = local.replace(minute=minute, second=0, microsecond=0)
        self._quarter_start = dt_util.as_utc(local_start)
        self._energy_ws = 0.0
        self._covered_seconds = 0.0
        self._quarter_profile = self.profile
        self._profile_changed_in_quarter = False
        self._last_sample_time = dt_util.as_utc(now_utc)

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

    async def _finalize_quarter(self, end_utc: datetime) -> None:
        if self._quarter_start is None:
            return
        duration = max(1.0, (end_utc - self._quarter_start).total_seconds())
        coverage = min(1.0, self._covered_seconds / duration)
        measurement_valid = coverage >= MIN_VALID_COVERAGE
        final_profile = PROFILE_MIXED if self._profile_changed_in_quarter else self._quarter_profile
        learning_valid = (
            measurement_valid
            and not self._profile_changed_in_quarter
            and final_profile in PROFILE_LEARNING_OPTIONS
        )
        if not measurement_valid:
            blocker = "insufficient_coverage"
        elif self._profile_changed_in_quarter:
            blocker = "profile_changed"
        elif final_profile == PROFILE_UNCLASSIFIED:
            blocker = "profile_unclassified"
        elif final_profile not in PROFILE_LEARNING_OPTIONS:
            blocker = "profile_not_learnable"
        else:
            blocker = None

        energy_kwh = self._energy_ws / 3_600_000 if measurement_valid else None
        result = QuarterResult(
            start=self._quarter_start,
            end=end_utc,
            energy_kwh=round(energy_kwh, 6) if energy_kwh is not None else None,
            coverage=round(coverage, 4),
            profile=final_profile,
            measurement_valid=measurement_valid,
            learning_valid=learning_valid,
            learning_blocker=blocker,
        )
        self.last_quarter = result
        self.records.append(
            {
                "start": result.start.isoformat(),
                "end": result.end.isoformat(),
                "energy_kwh": result.energy_kwh,
                "coverage": result.coverage,
                "profile": result.profile,
                "measurement_valid": result.measurement_valid,
                "learning_valid": result.learning_valid,
                "learning_blocker": result.learning_blocker,
                "valid": result.valid,
            }
        )
        self._prune_records()

    async def async_set_profile(
        self,
        profile: str,
        *,
        source: str = "manual_select",
        now: datetime | None = None,
    ) -> None:
        if profile not in PROFILE_LEARNING_OPTIONS:
            raise ValueError(f"Unsupported learning profile: {profile}")
        if profile == self.profile:
            return
        now_utc = dt_util.as_utc(now or dt_util.utcnow())
        await self._advance_through_elapsed_boundaries(now_utc)
        self._integrate_until(now_utc)
        old_profile = self.profile
        at_quarter_start = (
            self._quarter_start is not None
            and abs((now_utc - self._quarter_start).total_seconds()) <= 1e-6
            and self._covered_seconds == 0.0
            and self._energy_ws == 0.0
        )
        if at_quarter_start:
            self._quarter_profile = profile
        else:
            self._profile_changed_in_quarter = True
        self.previous_profile = old_profile
        self.profile = profile
        self.profile_changed_at = now_utc.isoformat()
        self.profile_change_source = source
        await self._async_save()
        self._notify()

    async def _async_save(self) -> None:
        await self.store.async_save(
            {
                "energy_store_schema_version": ENERGY_STORE_SCHEMA_VERSION,
                "source_signature": self._source_signature,
                "source_mode": self.source_mode,
                "profile": self.profile,
                "previous_profile": self.previous_profile,
                "profile_changed_at": self.profile_changed_at,
                "profile_change_source": self.profile_change_source,
                "records": self.records,
            }
        )

    def _prune_records(self) -> None:
        cutoff = dt_util.utcnow() - timedelta(days=MAX_HISTORY_DAYS)
        kept: list[dict[str, Any]] = []
        for record in self.records:
            try:
                start = datetime.fromisoformat(str(record["start"]))
            except (KeyError, TypeError, ValueError):
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=dt_util.UTC)
            if dt_util.as_utc(start) >= cutoff:
                kept.append(record)
        self.records = kept

    @property
    def history_days(self) -> int:
        dates: set[str] = set()
        for record in self.records:
            if not record.get("valid"):
                continue
            try:
                start = datetime.fromisoformat(str(record["start"]))
            except (KeyError, TypeError, ValueError):
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=dt_util.UTC)
            dates.add(dt_util.as_local(start).date().isoformat())
        return len(dates)

    @property
    def valid_quarters(self) -> int:
        return sum(1 for record in self.records if record.get("valid"))

    def forecast(self, *, now: datetime | None = None):
        """Return the current native 288-slot Energy Forecast."""
        reference = dt_util.as_utc(now or dt_util.utcnow())
        model = EnergyBaselineForecast(self.records, local_timezone=dt_util.DEFAULT_TIME_ZONE)
        return model.build(self.profile, now=reference)

    def profile_statistics(self) -> dict[str, Any]:
        model = EnergyBaselineForecast(self.records, local_timezone=dt_util.DEFAULT_TIME_ZONE)
        return model.profile_statistics(self.profile)
