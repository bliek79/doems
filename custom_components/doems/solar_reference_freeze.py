"""Pure Alpha41 Solar reference-freeze validation and snapshot helpers."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from typing import Any, Mapping

REFERENCE_RELEASE = "0.2.0-alpha.41"
REFERENCE_COMMIT = "0dbf9dd68345d9a5dd96d82591aa1d8b93689415"
REFERENCE_REPOSITORY = "bliek79/dummy-os-energy"
REFERENCE_MODEL = "open_meteo_gti_physical_v0.1"
REFERENCE_PROVIDER_MODEL = "best_match"
REFERENCE_RESOLUTION_MINUTES = 15
REFERENCE_HORIZON_HOURS = 72
REFERENCE_SLOT_COUNT = 288
REFERENCE_POINT_INTERVAL_MS = 15 * 60 * 1000
REFERENCE_POINT_FORMAT = (
    "[unix_ms, north_kwh, south_kwh, total_kwh, north_kw, south_kw, "
    "total_kw, north_gti_wm2, south_gti_wm2]"
)
REFERENCE_STORAGE_SCHEMA = 1

ENTITY_STATUS = "sensor.do_solar_status"
ENTITY_TIMELINE = "sensor.do_solar_forecast_timeline"
ENTITY_MODEL = "sensor.do_solar_model"
ENTITY_NEXT_QUARTER = "sensor.do_solar_forecast_next_quarter"
ENTITY_ACTUAL_NORTH = "sensor.do_solar_actual_power_north"
ENTITY_ACTUAL_SOUTH = "sensor.do_solar_actual_power_south"
ENTITY_ACTUAL_TOTAL = "sensor.do_solar_actual_power_total"
ENTITY_TODAY_NORTH = "sensor.do_solar_forecast_today_north"
ENTITY_TODAY_SOUTH = "sensor.do_solar_forecast_today_south"
ENTITY_TODAY_TOTAL = "sensor.do_solar_forecast_today_total"
ENTITY_TOMORROW_NORTH = "sensor.do_solar_forecast_tomorrow_north"
ENTITY_TOMORROW_SOUTH = "sensor.do_solar_forecast_tomorrow_south"
ENTITY_TOMORROW_TOTAL = "sensor.do_solar_forecast_tomorrow_total"

REFERENCE_ENTITY_IDS = (
    ENTITY_STATUS,
    ENTITY_TIMELINE,
    ENTITY_MODEL,
    ENTITY_NEXT_QUARTER,
    ENTITY_ACTUAL_NORTH,
    ENTITY_ACTUAL_SOUTH,
    ENTITY_ACTUAL_TOTAL,
    ENTITY_TODAY_NORTH,
    ENTITY_TODAY_SOUTH,
    ENTITY_TODAY_TOTAL,
    ENTITY_TOMORROW_NORTH,
    ENTITY_TOMORROW_SOUTH,
    ENTITY_TOMORROW_TOTAL,
)

NUMERIC_STATE_ENTITIES = (
    ENTITY_NEXT_QUARTER,
    ENTITY_ACTUAL_NORTH,
    ENTITY_ACTUAL_SOUTH,
    ENTITY_ACTUAL_TOTAL,
    ENTITY_TODAY_NORTH,
    ENTITY_TODAY_SOUTH,
    ENTITY_TODAY_TOTAL,
    ENTITY_TOMORROW_NORTH,
    ENTITY_TOMORROW_SOUTH,
    ENTITY_TOMORROW_TOTAL,
)


def _record(states: Mapping[str, Mapping[str, Any]], entity_id: str) -> Mapping[str, Any] | None:
    item = states.get(entity_id)
    return item if isinstance(item, Mapping) else None


def _attrs(record: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if record is None:
        return {}
    value = record.get("attributes", {})
    return value if isinstance(value, Mapping) else {}


def _finite_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    number = _finite_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def validate_reference(states: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Return deterministic blockers; an empty list means the live reference is capture-ready."""
    blockers: list[str] = []

    for entity_id in REFERENCE_ENTITY_IDS:
        record = _record(states, entity_id)
        if record is None:
            blockers.append(f"missing_entity:{entity_id}")
            continue
        if str(record.get("state", "")) in {"", "unknown", "unavailable", "none", "None"}:
            blockers.append(f"unavailable_entity:{entity_id}")

    status = _record(states, ENTITY_STATUS)
    if status is not None and str(status.get("state")) != "ok":
        blockers.append(f"source_status_not_ok:{status.get('state')}")

    model = _record(states, ENTITY_MODEL)
    if model is not None and str(model.get("state")) != REFERENCE_MODEL:
        blockers.append(f"unexpected_model:{model.get('state')}")

    timeline = _record(states, ENTITY_TIMELINE)
    timeline_attrs = _attrs(timeline)
    if timeline is not None:
        if _integer(timeline.get("state")) != REFERENCE_SLOT_COUNT:
            blockers.append("timeline_state_not_288")
        if _integer(timeline_attrs.get("resolution_minutes")) != REFERENCE_RESOLUTION_MINUTES:
            blockers.append("timeline_resolution_not_15")
        if _integer(timeline_attrs.get("horizon_hours")) != REFERENCE_HORIZON_HOURS:
            blockers.append("timeline_horizon_not_72")
        if _integer(timeline_attrs.get("slot_count")) != REFERENCE_SLOT_COUNT:
            blockers.append("timeline_slot_count_not_288")
        if _integer(timeline_attrs.get("point_count")) != REFERENCE_SLOT_COUNT:
            blockers.append("timeline_point_count_not_288")
        if str(timeline_attrs.get("point_format")) != REFERENCE_POINT_FORMAT:
            blockers.append("timeline_point_format_mismatch")
        if str(timeline_attrs.get("model")) != REFERENCE_PROVIDER_MODEL:
            blockers.append("timeline_provider_model_mismatch")

        points = timeline_attrs.get("points")
        if not isinstance(points, list) or len(points) != REFERENCE_SLOT_COUNT:
            blockers.append("timeline_raw_points_not_288")
        else:
            previous_ms: int | None = None
            for index, point in enumerate(points):
                if not isinstance(point, list) or len(point) != 9:
                    blockers.append(f"timeline_point_shape:{index}")
                    break
                timestamp = _integer(point[0])
                if timestamp is None:
                    blockers.append(f"timeline_timestamp_invalid:{index}")
                    break
                if any(_finite_number(value) is None for value in point[1:]):
                    blockers.append(f"timeline_value_invalid:{index}")
                    break
                if previous_ms is not None and timestamp - previous_ms != REFERENCE_POINT_INTERVAL_MS:
                    blockers.append(f"timeline_interval_invalid:{index}")
                    break
                previous_ms = timestamp

            start = _aware_datetime(timeline_attrs.get("forecast_start"))
            end = _aware_datetime(timeline_attrs.get("forecast_end"))
            if start is None or end is None:
                blockers.append("timeline_window_timestamp_invalid")
            elif int((end - start).total_seconds()) != REFERENCE_HORIZON_HOURS * 3600:
                blockers.append("timeline_window_not_72h")
            elif points:
                first_ms = _integer(points[0][0])
                last_ms = _integer(points[-1][0])
                if first_ms != int(start.timestamp() * 1000):
                    blockers.append("timeline_first_point_mismatch")
                expected_last = int((end.timestamp() * 1000) - REFERENCE_POINT_INTERVAL_MS)
                if last_ms != expected_last:
                    blockers.append("timeline_last_point_mismatch")

    for entity_id in NUMERIC_STATE_ENTITIES:
        record = _record(states, entity_id)
        if record is not None and _finite_number(record.get("state")) is None:
            blockers.append(f"numeric_state_invalid:{entity_id}")

    next_quarter = _record(states, ENTITY_NEXT_QUARTER)
    if next_quarter is not None:
        attrs = _attrs(next_quarter)
        if _aware_datetime(attrs.get("start")) is None:
            blockers.append("next_quarter_start_invalid")
        if _finite_number(attrs.get("north_kwh")) is None:
            blockers.append("next_quarter_north_invalid")
        if _finite_number(attrs.get("south_kwh")) is None:
            blockers.append("next_quarter_south_invalid")

    return list(dict.fromkeys(blockers))


def _value_record(states: Mapping[str, Mapping[str, Any]], entity_id: str) -> dict[str, Any]:
    record = _record(states, entity_id) or {}
    return {
        "entity_id": entity_id,
        "state": record.get("state"),
        "attributes": dict(_attrs(record)),
    }


def build_snapshot(
    states: Mapping[str, Mapping[str, Any]],
    *,
    captured_at_utc: datetime,
    captured_at_local: datetime,
) -> dict[str, Any]:
    """Build one immutable JSON-safe reference snapshot after validation succeeds."""
    blockers = validate_reference(states)
    if blockers:
        raise ValueError("reference_not_ready:" + ",".join(blockers))
    if captured_at_utc.tzinfo is None or captured_at_local.tzinfo is None:
        raise ValueError("timezone_aware_capture_required")

    timeline = _record(states, ENTITY_TIMELINE) or {}
    timeline_attrs = _attrs(timeline)
    points = timeline_attrs.get("points")
    assert isinstance(points, list)
    canonical_points = json.dumps(
        points,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    timeline_sha256 = hashlib.sha256(canonical_points).hexdigest()
    capture_utc = captured_at_utc.isoformat()
    capture_local = captured_at_local.isoformat()
    snapshot_id = captured_at_utc.strftime("A41-SOLAR-%Y%m%dT%H%M%SZ")

    return {
        "schema_version": REFERENCE_STORAGE_SCHEMA,
        "snapshot_id": snapshot_id,
        "captured_at_utc": capture_utc,
        "captured_at_local": capture_local,
        "reference": {
            "release": REFERENCE_RELEASE,
            "commit": REFERENCE_COMMIT,
            "repository": REFERENCE_REPOSITORY,
        },
        "contract": {
            "resolution_minutes": REFERENCE_RESOLUTION_MINUTES,
            "horizon_hours": REFERENCE_HORIZON_HOURS,
            "slot_count": REFERENCE_SLOT_COUNT,
            "point_format": REFERENCE_POINT_FORMAT,
            "physical_execution_authority": False,
        },
        "source_status": _value_record(states, ENTITY_STATUS),
        "model": _value_record(states, ENTITY_MODEL),
        "actual": {
            "north": _value_record(states, ENTITY_ACTUAL_NORTH),
            "south": _value_record(states, ENTITY_ACTUAL_SOUTH),
            "total": _value_record(states, ENTITY_ACTUAL_TOTAL),
        },
        "next_quarter": _value_record(states, ENTITY_NEXT_QUARTER),
        "today": {
            "north": _value_record(states, ENTITY_TODAY_NORTH),
            "south": _value_record(states, ENTITY_TODAY_SOUTH),
            "total": _value_record(states, ENTITY_TODAY_TOTAL),
        },
        "tomorrow": {
            "north": _value_record(states, ENTITY_TOMORROW_NORTH),
            "south": _value_record(states, ENTITY_TOMORROW_SOUTH),
            "total": _value_record(states, ENTITY_TOMORROW_TOTAL),
        },
        "timeline": {
            "state": timeline.get("state"),
            "source": timeline_attrs.get("source"),
            "provider_model": timeline_attrs.get("model"),
            "resolution_minutes": timeline_attrs.get("resolution_minutes"),
            "horizon_hours": timeline_attrs.get("horizon_hours"),
            "slot_count": timeline_attrs.get("slot_count"),
            "point_count": timeline_attrs.get("point_count"),
            "source_buffer_point_count": timeline_attrs.get("source_buffer_point_count"),
            "point_format": timeline_attrs.get("point_format"),
            "interval_semantics": timeline_attrs.get("interval_semantics"),
            "forecast_start": timeline_attrs.get("forecast_start"),
            "last_slot_start": timeline_attrs.get("last_slot_start"),
            "forecast_end": timeline_attrs.get("forecast_end"),
            "raw_points_sha256": timeline_sha256,
            "points": points,
        },
        "sheets_anchor": {
            "mode": "read_only",
            "status": "pending_verification",
            "anchor_utc": capture_utc,
            "anchor_local": capture_local,
        },
    }
