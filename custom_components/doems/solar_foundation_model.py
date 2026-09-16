"""Pure Solar P3.0 Foundation topology contract for DOEMS."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from .const import (
    CONF_SOLAR_ARRAYS,
    CONF_SOLAR_FOUNDATION_ENABLED,
    CONF_SOLAR_INVERTER_GROUPS,
    CONF_SOLAR_LATITUDE,
    CONF_SOLAR_LOCATION_SOURCE,
    CONF_SOLAR_LONGITUDE,
    CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY,
    SOLAR_FOUNDATION_SCHEMA_VERSION,
    SOLAR_LOCATION_HOME_ASSISTANT,
    SOLAR_LOCATION_OVERRIDE,
    SOLAR_PROVIDER,
)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_solar_foundation(
    options: dict[str, Any],
    *,
    ha_latitude: float | None,
    ha_longitude: float | None,
) -> list[str]:
    """Return structural blockers for one generic Solar install contract."""
    if not options.get(CONF_SOLAR_FOUNDATION_ENABLED, False):
        return []

    blockers: list[str] = []
    location_source = options.get(CONF_SOLAR_LOCATION_SOURCE, SOLAR_LOCATION_HOME_ASSISTANT)
    if location_source not in {SOLAR_LOCATION_HOME_ASSISTANT, SOLAR_LOCATION_OVERRIDE}:
        blockers.append("location_source_invalid")

    latitude = ha_latitude if location_source == SOLAR_LOCATION_HOME_ASSISTANT else _float(options.get(CONF_SOLAR_LATITUDE))
    longitude = ha_longitude if location_source == SOLAR_LOCATION_HOME_ASSISTANT else _float(options.get(CONF_SOLAR_LONGITUDE))
    if latitude is None or not -90 <= latitude <= 90:
        blockers.append("latitude_invalid")
    if longitude is None or not -180 <= longitude <= 180:
        blockers.append("longitude_invalid")

    groups = options.get(CONF_SOLAR_INVERTER_GROUPS, [])
    arrays = options.get(CONF_SOLAR_ARRAYS, [])
    if not isinstance(groups, list) or not groups:
        blockers.append("inverter_group_missing")
        groups = []
    if not isinstance(arrays, list) or not arrays:
        blockers.append("array_missing")
        arrays = []

    group_ids: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            blockers.append("inverter_group_invalid")
            continue
        group_id = str(group.get("group_id") or "")
        if not group_id:
            blockers.append("group_id_missing")
        elif group_id in group_ids:
            blockers.append(f"group_id_duplicate:{group_id}")
        else:
            group_ids.append(group_id)
        ac_limit = _float(group.get("ac_limit_kw", 0.0))
        if ac_limit is None or ac_limit < 0:
            blockers.append(f"group_ac_limit_invalid:{group_id or '?'}")

    array_ids: list[str] = []
    actual_entities: list[str] = []
    total_actual = str(options.get(CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY) or "")
    for array in arrays:
        if not isinstance(array, dict):
            blockers.append("array_invalid")
            continue
        array_id = str(array.get("array_id") or "")
        group_id = str(array.get("group_id") or "")
        if not array_id:
            blockers.append("array_id_missing")
        elif array_id in array_ids:
            blockers.append(f"array_id_duplicate:{array_id}")
        else:
            array_ids.append(array_id)
        if group_id not in group_ids:
            blockers.append(f"array_group_unknown:{array_id or '?'}")
        dc_kwp = _float(array.get("dc_kwp"))
        tilt_deg = _float(array.get("tilt_deg"))
        azimuth_deg = _float(array.get("azimuth_deg"))
        if dc_kwp is None or dc_kwp <= 0:
            blockers.append(f"array_dc_kwp_invalid:{array_id or '?'}")
        if tilt_deg is None or not 0 <= tilt_deg <= 90:
            blockers.append(f"array_tilt_invalid:{array_id or '?'}")
        if azimuth_deg is None or not 0 <= azimuth_deg < 360:
            blockers.append(f"array_azimuth_invalid:{array_id or '?'}")
        actual = str(array.get("actual_power_entity") or "")
        if actual:
            if actual in actual_entities:
                blockers.append(f"array_actual_duplicate:{actual}")
            actual_entities.append(actual)
            if len(arrays) > 1 and total_actual and actual == total_actual:
                blockers.append(f"total_actual_reused_as_array:{array_id or '?'}")

    return sorted(set(blockers))


def build_solar_foundation_snapshot(
    options: dict[str, Any],
    *,
    ha_latitude: float | None,
    ha_longitude: float | None,
) -> dict[str, Any]:
    """Build the normalized, provider-neutral Solar topology snapshot."""
    enabled = bool(options.get(CONF_SOLAR_FOUNDATION_ENABLED, False))
    location_source = options.get(CONF_SOLAR_LOCATION_SOURCE, SOLAR_LOCATION_HOME_ASSISTANT)
    latitude = ha_latitude if location_source == SOLAR_LOCATION_HOME_ASSISTANT else _float(options.get(CONF_SOLAR_LATITUDE))
    longitude = ha_longitude if location_source == SOLAR_LOCATION_HOME_ASSISTANT else _float(options.get(CONF_SOLAR_LONGITUDE))
    groups = [dict(item) for item in options.get(CONF_SOLAR_INVERTER_GROUPS, []) if isinstance(item, dict)]
    arrays = [dict(item) for item in options.get(CONF_SOLAR_ARRAYS, []) if isinstance(item, dict)]
    blockers = validate_solar_foundation(options, ha_latitude=ha_latitude, ha_longitude=ha_longitude)

    total_dc_kwp = round(sum(float(item.get("dc_kwp", 0.0)) for item in arrays if _float(item.get("dc_kwp")) is not None), 6)
    known_ac = [float(item.get("ac_limit_kw", 0.0)) for item in groups if (_float(item.get("ac_limit_kw")) or 0.0) > 0]
    known_ac_limit_kw = round(sum(known_ac), 6)
    total_actual = str(options.get(CONF_SOLAR_TOTAL_ACTUAL_POWER_ENTITY) or "") or None
    per_array_actual_count = sum(1 for item in arrays if item.get("actual_power_entity"))

    signature_payload = {
        "schema_version": SOLAR_FOUNDATION_SCHEMA_VERSION,
        "provider": SOLAR_PROVIDER,
        "location": {"source": location_source, "latitude": latitude, "longitude": longitude},
        "groups": [
            {"group_id": item.get("group_id"), "ac_limit_kw": item.get("ac_limit_kw", 0.0)}
            for item in groups
        ],
        "arrays": [
            {
                "array_id": item.get("array_id"),
                "group_id": item.get("group_id"),
                "dc_kwp": item.get("dc_kwp"),
                "tilt_deg": item.get("tilt_deg"),
                "azimuth_deg": item.get("azimuth_deg"),
                "actual_power_entity": item.get("actual_power_entity") or None,
            }
            for item in arrays
        ],
        "total_actual_power_entity": total_actual,
    }
    topology_signature = sha256(
        json.dumps(signature_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()

    return {
        "status": "disabled" if not enabled else ("ready" if not blockers else "invalid"),
        "enabled": enabled,
        "schema_version": SOLAR_FOUNDATION_SCHEMA_VERSION,
        "provider": SOLAR_PROVIDER,
        "location_source": location_source,
        "latitude": latitude,
        "longitude": longitude,
        "azimuth_contract": "0=N,90=E,180=S,270=W_clockwise_from_true_north",
        "inverter_group_count": len(groups),
        "array_count": len(arrays),
        "total_dc_kwp": total_dc_kwp,
        "known_ac_limit_kw": known_ac_limit_kw,
        "ac_limits_complete": bool(groups) and len(known_ac) == len(groups),
        "total_actual_configured": total_actual is not None,
        "total_actual_power_entity": total_actual,
        "per_array_actual_count": per_array_actual_count,
        "inverter_groups": groups,
        "arrays": arrays,
        "blockers": blockers,
        "topology_signature": topology_signature,
        "physical_execution_authority": False,
        "forecast_runtime_active": False,
        "native_time_contract": {"resolution_minutes": 15, "horizon_hours": 72, "slot_count": 288},
    }
