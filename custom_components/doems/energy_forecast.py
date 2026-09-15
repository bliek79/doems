"""Pure 15-minute / 72-hour Energy Forecast model for DOEMS."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from math import pow
from typing import Any

from .const import (
    FORECAST_SLOTS,
    PROFILE_LEARNING_OPTIONS,
    QUARTER_MINUTES,
    RECENCY_HALF_LIFE_DAYS,
)

MAX_INTERNAL_FORECAST_SLOTS = FORECAST_SLOTS + 3
STEP = timedelta(minutes=QUARTER_MINUTES)


def utc(value: datetime) -> datetime:
    """Return one aware timestamp in UTC."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


def floor_quarter(value: datetime) -> datetime:
    """Floor an aware timestamp to the native UTC quarter."""
    value = utc(value)
    return value.replace(minute=value.minute // QUARTER_MINUTES * QUARTER_MINUTES, second=0, microsecond=0)


def ceil_quarter(value: datetime) -> datetime:
    """Ceil an aware timestamp, keeping an exact quarter boundary unchanged."""
    value = utc(value)
    floor = floor_quarter(value)
    return floor if floor == value else floor + STEP


@dataclass(slots=True)
class HistoricalSample:
    """One valid historical quarter used by the forecast model."""

    start: datetime
    energy_kwh: float


@dataclass(slots=True)
class ForecastSlot:
    """One 15-minute forecast slot."""

    start: datetime
    end: datetime
    energy_kwh: float | None
    sample_count: int
    source: str
    confidence: float


class EnergyBaselineForecast:
    """Build the Alpha41-equivalent rolling 72-hour history-driven forecast."""

    def __init__(self, records: list[dict[str, Any]], *, local_timezone: tzinfo) -> None:
        self.records = records
        self.local_timezone = local_timezone

    @staticmethod
    def _quarter_index(local_dt: datetime) -> int:
        return local_dt.hour * 4 + local_dt.minute // QUARTER_MINUTES

    @staticmethod
    def _day_type(local_dt: datetime) -> str:
        return "weekend" if local_dt.weekday() >= 5 else "weekday"

    @staticmethod
    def _recency_weight(sample_start: datetime, reference: datetime) -> float:
        age_days = max(0.0, (reference - sample_start).total_seconds() / 86400.0)
        return pow(0.5, age_days / RECENCY_HALF_LIFE_DAYS)

    @classmethod
    def _weighted_mean(
        cls,
        samples: list[HistoricalSample],
        reference: datetime,
    ) -> float | None:
        if not samples:
            return None
        weighted_total = 0.0
        weight_total = 0.0
        for sample in samples:
            weight = cls._recency_weight(sample.start, reference)
            weighted_total += sample.energy_kwh * weight
            weight_total += weight
        if weight_total <= 0:
            return None
        return weighted_total / weight_total

    def _history(
        self,
        profile: str,
    ) -> tuple[
        dict[tuple[int, int], list[HistoricalSample]],
        dict[tuple[str, int], list[HistoricalSample]],
        dict[int, list[HistoricalSample]],
        list[HistoricalSample],
    ]:
        exact: dict[tuple[int, int], list[HistoricalSample]] = defaultdict(list)
        day_type: dict[tuple[str, int], list[HistoricalSample]] = defaultdict(list)
        quarter: dict[int, list[HistoricalSample]] = defaultdict(list)
        all_values: list[HistoricalSample] = []

        if profile not in PROFILE_LEARNING_OPTIONS:
            return exact, day_type, quarter, all_values

        for record in self.records:
            if not record.get("valid") or record.get("profile") != profile:
                continue
            value = record.get("energy_kwh")
            if value is None:
                continue
            try:
                start = datetime.fromisoformat(str(record["start"]))
                energy = float(value)
            except (KeyError, TypeError, ValueError):
                continue
            if start.tzinfo is None or start.utcoffset() is None:
                start = start.replace(tzinfo=timezone.utc)
            start = utc(start)
            local = start.astimezone(self.local_timezone)
            qidx = self._quarter_index(local)
            sample = HistoricalSample(start=start, energy_kwh=energy)
            exact[(local.weekday(), qidx)].append(sample)
            day_type[(self._day_type(local), qidx)].append(sample)
            quarter[qidx].append(sample)
            all_values.append(sample)

        return exact, day_type, quarter, all_values

    def profile_statistics(self, profile: str, *, reference: datetime | None = None) -> dict[str, Any]:
        """Return compact historical statistics for one profile."""
        exact, day_type, quarter, all_values = self._history(profile)
        ref = utc(reference or datetime.now(timezone.utc))
        weighted_mean = self._weighted_mean(all_values, ref)
        simple_mean = (
            sum(sample.energy_kwh for sample in all_values) / len(all_values)
            if all_values
            else None
        )
        return {
            "profile": profile,
            "valid_samples": len(all_values),
            "weekday_quarter_cells": len(exact),
            "weekday_quarter_coverage": round(len(exact) / (7 * 96), 4),
            "day_type_quarter_cells": len(day_type),
            "day_type_quarter_coverage": round(len(day_type) / (2 * 96), 4),
            "quarter_cells": len(quarter),
            "quarter_coverage": round(len(quarter) / 96, 4),
            "mean_quarter_kwh": round(simple_mean, 6) if simple_mean is not None else None,
            "weighted_mean_quarter_kwh": round(weighted_mean, 6) if weighted_mean is not None else None,
            "recency_half_life_days": RECENCY_HALF_LIFE_DAYS,
        }

    def build(
        self,
        profile: str,
        now: datetime | None = None,
        *,
        slot_count: int = FORECAST_SLOTS,
        window_start: datetime | None = None,
    ) -> list[ForecastSlot]:
        """Build native 15-minute forecast slots using the Alpha41 hierarchy."""
        if slot_count < 1 or slot_count > MAX_INTERNAL_FORECAST_SLOTS:
            raise ValueError(f"slot_count must be between 1 and {MAX_INTERNAL_FORECAST_SLOTS}")

        exact, day_type, quarter, all_values = self._history(profile)
        now_utc = utc(now or datetime.now(timezone.utc))
        start_utc = utc(window_start) if window_start is not None else ceil_quarter(now_utc)
        if start_utc != floor_quarter(start_utc):
            raise ValueError("forecast window start must be quarter-aligned")

        result: list[ForecastSlot] = []
        for offset in range(slot_count):
            slot_start_utc = start_utc + timedelta(minutes=offset * QUARTER_MINUTES)
            slot_end_utc = slot_start_utc + STEP
            slot_start_local = slot_start_utc.astimezone(self.local_timezone)
            qidx = self._quarter_index(slot_start_local)
            exact_values = exact.get((slot_start_local.weekday(), qidx), [])
            day_type_values = day_type.get((self._day_type(slot_start_local), qidx), [])
            quarter_values = quarter.get(qidx, [])

            if exact_values:
                value = self._weighted_mean(exact_values, now_utc)
                samples = len(exact_values)
                source = "weekday_quarter"
                confidence = min(0.98, 0.58 + 0.08 * min(samples, 5))
            elif day_type_values:
                value = self._weighted_mean(day_type_values, now_utc)
                samples = len(day_type_values)
                source = "day_type_quarter"
                confidence = min(0.78, 0.42 + 0.07 * min(samples, 5))
            elif quarter_values:
                value = self._weighted_mean(quarter_values, now_utc)
                samples = len(quarter_values)
                source = "quarter_of_day"
                confidence = min(0.55, 0.25 + 0.06 * min(samples, 5))
            elif all_values:
                value = self._weighted_mean(all_values, now_utc)
                samples = len(all_values)
                source = "profile_mean"
                confidence = min(0.25, 0.10 + 0.01 * min(samples, 15))
            else:
                value = None
                samples = 0
                source = "profile_unclassified" if profile not in PROFILE_LEARNING_OPTIONS else "unavailable"
                confidence = 0.0

            result.append(
                ForecastSlot(
                    start=slot_start_utc,
                    end=slot_end_utc,
                    energy_kwh=round(value, 6) if value is not None else None,
                    sample_count=samples,
                    source=source,
                    confidence=round(confidence, 3),
                )
            )
        return result

    @staticmethod
    def average_confidence(slots: list[ForecastSlot]) -> float | None:
        """Return mean slot confidence as a percentage."""
        available = [slot.confidence for slot in slots if slot.energy_kwh is not None]
        if not available:
            return None
        return round(sum(available) / len(available) * 100.0, 1)

    @staticmethod
    def serialize(slots: list[ForecastSlot]) -> list[dict[str, Any]]:
        """Serialize forecast slots for diagnostics/tests."""
        return [
            {
                "start": slot.start.isoformat(),
                "end": slot.end.isoformat(),
                "energy_kwh": slot.energy_kwh,
                "sample_count": slot.sample_count,
                "source": slot.source,
                "confidence": slot.confidence,
            }
            for slot in slots
        ]
