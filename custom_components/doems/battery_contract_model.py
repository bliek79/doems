"""Pure battery input contract evaluation for DOEMS."""

from __future__ import annotations

from typing import Any, Mapping

UNKNOWN_STATES = {"", "unknown", "unavailable", "none", "null"}
ALLOWED_DEVICE_STATUSES = {"standby", "charging", "discharging", "sleep"}
SIMULTANEOUS_POWER_TOLERANCE_W = 1.0


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in UNKNOWN_STATES:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def normalize_soc_percent(value: Any, unit: Any) -> float | None:
    """Normalize a SOC source to percentage points."""
    if str(unit or "").strip() != "%":
        return None
    numeric = _as_float(value)
    if numeric is None or numeric < 0.0 or numeric > 100.0:
        return None
    return round(numeric, 3)


def normalize_capacity_kwh(value: Any, unit: Any) -> float | None:
    """Normalize a positive battery-capacity source to kWh."""
    numeric = _as_float(value)
    if numeric is None or numeric <= 0.0:
        return None
    normalized_unit = str(unit or "").strip().lower()
    if normalized_unit == "kwh":
        return round(numeric, 6)
    if normalized_unit == "wh":
        return round(numeric / 1000.0, 6)
    return None


def normalize_positive_power_w(value: Any, unit: Any) -> float | None:
    """Normalize a positive power magnitude to W."""
    numeric = _as_float(value)
    if numeric is None or numeric < 0.0:
        return None
    normalized_unit = str(unit or "").strip().lower()
    if normalized_unit == "w":
        return round(numeric, 3)
    if normalized_unit == "kw":
        return round(numeric * 1000.0, 3)
    return None


def _source_missing(raw: Mapping[str, Any]) -> bool:
    return not str(raw.get("entity_id") or "").strip()


def _source_unavailable(raw: Mapping[str, Any]) -> bool:
    state = raw.get("state")
    if state is None:
        return True
    return str(state).strip().lower() in UNKNOWN_STATES


def evaluate_battery_input_contract(
    sources: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate the read-only battery observation contract."""
    blockers: list[str] = []
    warnings: list[str] = []

    for role in ("soc", "capacity", "charge_power", "discharge_power", "device_status"):
        raw = sources.get(role, {})
        if _source_missing(raw):
            blockers.append(f"{role}_source_not_configured")
        elif _source_unavailable(raw):
            blockers.append(f"{role}_source_unavailable")

    soc_raw = sources.get("soc", {})
    capacity_raw = sources.get("capacity", {})
    charge_raw = sources.get("charge_power", {})
    discharge_raw = sources.get("discharge_power", {})
    status_raw = sources.get("device_status", {})

    soc = None if _source_missing(soc_raw) or _source_unavailable(soc_raw) else normalize_soc_percent(
        soc_raw.get("state"), soc_raw.get("unit")
    )
    capacity = None if _source_missing(capacity_raw) or _source_unavailable(capacity_raw) else normalize_capacity_kwh(
        capacity_raw.get("state"), capacity_raw.get("unit")
    )
    charge = None if _source_missing(charge_raw) or _source_unavailable(charge_raw) else normalize_positive_power_w(
        charge_raw.get("state"), charge_raw.get("unit")
    )
    discharge = None if _source_missing(discharge_raw) or _source_unavailable(discharge_raw) else normalize_positive_power_w(
        discharge_raw.get("state"), discharge_raw.get("unit")
    )
    device_status = None
    if not _source_missing(status_raw) and not _source_unavailable(status_raw):
        device_status = str(status_raw.get("state") or "").strip().lower()

    if not _source_missing(soc_raw) and not _source_unavailable(soc_raw) and soc is None:
        blockers.append("soc_value_or_unit_invalid")
    if not _source_missing(capacity_raw) and not _source_unavailable(capacity_raw) and capacity is None:
        blockers.append("capacity_value_or_unit_invalid")
    if not _source_missing(charge_raw) and not _source_unavailable(charge_raw) and charge is None:
        blockers.append("charge_power_value_or_unit_invalid")
    if not _source_missing(discharge_raw) and not _source_unavailable(discharge_raw) and discharge is None:
        blockers.append("discharge_power_value_or_unit_invalid")
    if (
        not _source_missing(status_raw)
        and not _source_unavailable(status_raw)
        and device_status not in ALLOWED_DEVICE_STATUSES
    ):
        blockers.append("device_status_invalid")

    direction_consistent = True
    if charge is not None and discharge is not None:
        direction_consistent = not (
            charge > SIMULTANEOUS_POWER_TOLERANCE_W
            and discharge > SIMULTANEOUS_POWER_TOLERANCE_W
        )
        if not direction_consistent:
            blockers.append("simultaneous_charge_and_discharge")

    status_direction_consistent: bool | None = None
    if device_status in ALLOWED_DEVICE_STATUSES and charge is not None and discharge is not None:
        status_direction_consistent = True
        if device_status == "charging" and discharge > SIMULTANEOUS_POWER_TOLERANCE_W:
            status_direction_consistent = False
        elif device_status == "discharging" and charge > SIMULTANEOUS_POWER_TOLERANCE_W:
            status_direction_consistent = False
        elif device_status in {"standby", "sleep"} and (
            charge > SIMULTANEOUS_POWER_TOLERANCE_W
            or discharge > SIMULTANEOUS_POWER_TOLERANCE_W
        ):
            status_direction_consistent = False
        if status_direction_consistent is False:
            warnings.append("device_status_power_direction_mismatch")

    ready_for_soc_projection = soc is not None and capacity is not None
    status = "ready" if not blockers else "blocked"

    return {
        "status": status,
        "ready_for_soc_projection": ready_for_soc_projection,
        "read_only": True,
        "physical_execution_authority": False,
        "contract_version": 1,
        "soc_percent": soc,
        "capacity_kwh": capacity,
        "charge_power_w": charge,
        "discharge_power_w": discharge,
        "device_status": device_status,
        "direction_consistent": direction_consistent,
        "status_direction_consistent": status_direction_consistent,
        "blockers": blockers,
        "warnings": warnings,
        "source_entities": {
            role: str(sources.get(role, {}).get("entity_id") or "") or None
            for role in ("soc", "capacity", "charge_power", "discharge_power", "device_status")
        },
        "capacity_source_provenance": "configured_home_assistant_entity",
    }
