"""Pure provider-neutral Solar P3.1 forecast calculation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Mapping, Sequence

SOLAR_FORECAST_MODEL = "open_meteo_gti_physical_v0.1"
SOLAR_PERFORMANCE_FACTOR = 0.90
SOLAR_RESOLUTION_MINUTES = 15
SOLAR_HORIZON_HOURS = 72
SOLAR_FORECAST_SLOTS = SOLAR_HORIZON_HOURS * 60 // SOLAR_RESOLUTION_MINUTES


def _finite_float(value: Any, *, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{name}_invalid") from err
    if not math.isfinite(result):
        raise ValueError(f"{name}_invalid")
    return result


def canonical_to_open_meteo_azimuth(canonical_deg: float | int) -> float:
    """Map DOEMS 0=N/90=E/180=S/270=W to Open-Meteo 0=S convention."""
    canonical = _finite_float(canonical_deg, name="azimuth")
    if not 0.0 <= canonical < 360.0:
        raise ValueError("azimuth_invalid")
    mapped = (canonical - 180.0) % 360.0
    if mapped > 180.0:
        mapped -= 360.0
    return round(mapped, 6)


def next_complete_slot(timestamp: datetime, resolution_minutes: int = SOLAR_RESOLUTION_MINUTES) -> datetime:
    """Return the first complete slot boundary at or after timestamp using UTC arithmetic."""
    if timestamp.tzinfo is None:
        raise ValueError("timezone_aware_timestamp_required")
    resolution = int(resolution_minutes)
    if resolution <= 0:
        raise ValueError("resolution_invalid")
    reference = timestamp.astimezone(timezone.utc)
    floor_minute = (reference.minute // resolution) * resolution
    floor = reference.replace(minute=floor_minute, second=0, microsecond=0)
    result = floor if reference == floor else floor + timedelta(minutes=resolution)
    return result.astimezone(timestamp.tzinfo)


def backward_average_slot_start(timestamp: datetime, resolution_minutes: int = SOLAR_RESOLUTION_MINUTES) -> datetime:
    """Map an Open-Meteo backward-average timestamp to its energy-slot start."""
    if timestamp.tzinfo is None:
        raise ValueError("timezone_aware_timestamp_required")
    return timestamp - timedelta(minutes=int(resolution_minutes))


def slot_energy_kwh(power_kw: float | int, resolution_minutes: int = SOLAR_RESOLUTION_MINUTES) -> float:
    """Convert average slot power to slot energy."""
    power = _finite_float(power_kw, name="power_kw")
    resolution = int(resolution_minutes)
    if resolution <= 0:
        raise ValueError("resolution_invalid")
    return round(max(0.0, power) * resolution / 60.0, 6)


def array_power_kw(
    irradiance_wm2: float | int,
    dc_capacity_kwp: float | int,
    performance_factor: float = SOLAR_PERFORMANCE_FACTOR,
) -> float:
    """Convert plane-of-array irradiance to uncapped array AC-equivalent power."""
    irradiance = _finite_float(irradiance_wm2, name="irradiance")
    capacity = _finite_float(dc_capacity_kwp, name="dc_capacity_kwp")
    factor = _finite_float(performance_factor, name="performance_factor")
    if capacity <= 0.0:
        raise ValueError("dc_capacity_kwp_invalid")
    if factor < 0.0:
        raise ValueError("performance_factor_invalid")
    return round(max(0.0, irradiance) / 1000.0 * capacity * factor, 6)


@dataclass(frozen=True, slots=True)
class SolarForecastPoint:
    """One provider-neutral 15-minute system forecast point."""

    start: datetime
    array_ids: tuple[str, ...]
    array_kwh: tuple[float, ...]
    array_kw: tuple[float, ...]
    array_gti_wm2: tuple[float, ...]
    total_kwh: float
    total_kw: float
    group_kw: tuple[tuple[str, float], ...]
    clipped_groups: tuple[str, ...]

    def as_list(self) -> list[Any]:
        """Return compact stable-ID-indexed timeline representation."""
        return [
            int(self.start.timestamp() * 1000),
            self.total_kwh,
            self.total_kw,
            list(self.array_kwh),
            list(self.array_kw),
            list(self.array_gti_wm2),
        ]


def build_forecast_point(
    foundation: Mapping[str, Any],
    *,
    start: datetime,
    irradiance_by_array: Mapping[str, float | int],
    performance_factor: float = SOLAR_PERFORMANCE_FACTOR,
) -> SolarForecastPoint:
    """Build one generic 1..N Solar slot and enforce AC limits per inverter group."""
    if start.tzinfo is None:
        raise ValueError("timezone_aware_timestamp_required")

    arrays = foundation.get("arrays")
    groups = foundation.get("inverter_groups")
    if not isinstance(arrays, list) or not arrays:
        raise ValueError("array_missing")
    if not isinstance(groups, list) or not groups:
        raise ValueError("inverter_group_missing")

    group_limits: dict[str, float] = {}
    for group in groups:
        if not isinstance(group, Mapping):
            raise ValueError("inverter_group_invalid")
        group_id = str(group.get("group_id") or "")
        if not group_id:
            raise ValueError("group_id_missing")
        limit = _finite_float(group.get("ac_limit_kw", 0.0), name=f"group_ac_limit_kw:{group_id}")
        if limit < 0.0:
            raise ValueError(f"group_ac_limit_invalid:{group_id}")
        group_limits[group_id] = limit

    array_ids: list[str] = []
    group_members: dict[str, list[str]] = {group_id: [] for group_id in group_limits}
    raw_power: dict[str, float] = {}
    gti_values: dict[str, float] = {}

    for array in arrays:
        if not isinstance(array, Mapping):
            raise ValueError("array_invalid")
        array_id = str(array.get("array_id") or "")
        group_id = str(array.get("group_id") or "")
        if not array_id:
            raise ValueError("array_id_missing")
        if array_id in raw_power:
            raise ValueError(f"array_id_duplicate:{array_id}")
        if group_id not in group_limits:
            raise ValueError(f"array_group_unknown:{array_id}")
        if array_id not in irradiance_by_array:
            raise ValueError(f"irradiance_missing:{array_id}")

        gti = _finite_float(irradiance_by_array[array_id], name=f"irradiance:{array_id}")
        dc_kwp = _finite_float(array.get("dc_kwp"), name=f"dc_kwp:{array_id}")
        raw_power[array_id] = array_power_kw(gti, dc_kwp, performance_factor)
        gti_values[array_id] = max(0.0, gti)
        group_members[group_id].append(array_id)
        array_ids.append(array_id)

    final_power = dict(raw_power)
    clipped_groups: list[str] = []
    group_totals: list[tuple[str, float]] = []

    for group_id in group_limits:
        members = group_members[group_id]
        raw_total = sum(raw_power[array_id] for array_id in members)
        limit = group_limits[group_id]
        if limit > 0.0 and raw_total > limit and raw_total > 0.0:
            scale = limit / raw_total
            for array_id in members:
                final_power[array_id] = raw_power[array_id] * scale
            clipped_groups.append(group_id)
        group_total = sum(final_power[array_id] for array_id in members)
        group_totals.append((group_id, round(group_total, 6)))

    array_kw = tuple(round(final_power[array_id], 6) for array_id in array_ids)
    array_kwh = tuple(slot_energy_kwh(value) for value in array_kw)
    total_kw = round(sum(array_kw), 6)
    total_kwh = round(sum(array_kwh), 6)

    return SolarForecastPoint(
        start=start,
        array_ids=tuple(array_ids),
        array_kwh=array_kwh,
        array_kw=array_kw,
        array_gti_wm2=tuple(round(gti_values[array_id], 6) for array_id in array_ids),
        total_kwh=total_kwh,
        total_kw=total_kw,
        group_kw=tuple(group_totals),
        clipped_groups=tuple(clipped_groups),
    )


def build_forecast_timeline(
    foundation: Mapping[str, Any],
    *,
    starts: Sequence[datetime],
    irradiance_by_array: Mapping[str, Mapping[datetime, float | int]],
    performance_factor: float = SOLAR_PERFORMANCE_FACTOR,
) -> list[SolarForecastPoint]:
    """Build an aligned generic Solar timeline without nearest-neighbour padding."""
    arrays = foundation.get("arrays")
    if not isinstance(arrays, list) or not arrays:
        raise ValueError("array_missing")
    array_ids = [str(item.get("array_id") or "") for item in arrays if isinstance(item, Mapping)]
    if not array_ids or any(not array_id for array_id in array_ids):
        raise ValueError("array_id_missing")

    points: list[SolarForecastPoint] = []
    for start in starts:
        slot_gti: dict[str, float | int] = {}
        for array_id in array_ids:
            series = irradiance_by_array.get(array_id)
            if series is None or start not in series:
                raise ValueError(f"irradiance_missing:{array_id}:{start.isoformat()}")
            slot_gti[array_id] = series[start]
        points.append(
            build_forecast_point(
                foundation,
                start=start,
                irradiance_by_array=slot_gti,
                performance_factor=performance_factor,
            )
        )
    return points
