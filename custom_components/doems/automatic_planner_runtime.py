"""R5.1 multi-rate runtime helpers for the DOEMS automatic planner.

This module changes runtime orchestration only. The R5 planner policy remains in
automatic_planner_model.py and is intentionally not changed by the hotfix.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence

from .automatic_planner_model import build_automatic_plan
from .energy_forecast import EnergyBaselineForecast

RUNTIME_VERSION = "alpha6_1_cached_executor_v1"
PLANNER_POLICY_VERSION = "alpha6_automatic_planner_shadow_v1"


def _as_utc(reference: datetime) -> datetime:
    if reference.tzinfo is None:
        return reference.replace(tzinfo=timezone.utc)
    return reference.astimezone(timezone.utc)


def planner_cycle_id(reference: datetime) -> str:
    """Return the native 15-minute UTC planner cycle identity."""
    reference_utc = _as_utc(reference)
    minute = (reference_utc.minute // 15) * 15
    return reference_utc.replace(
        minute=minute,
        second=0,
        microsecond=0,
    ).isoformat()


def _stable_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def planner_request_signature(
    *,
    reference: datetime,
    source_markers: Mapping[str, Any],
    plans: Sequence[Mapping[str, Any]],
    start_soc_percent: float,
    capacity_kwh: float,
    settings: Mapping[str, Any],
) -> str:
    """Hash lightweight generation markers for event-loop deduplication."""
    return _stable_digest(
        {
            "runtime": RUNTIME_VERSION,
            "policy": PLANNER_POLICY_VERSION,
            "cycle": planner_cycle_id(reference),
            "sources": source_markers,
            "plans": list(plans),
            "soc": float(start_soc_percent),
            "capacity_kwh": float(capacity_kwh),
            "settings": dict(settings),
        }
    )


def planner_input_signature(
    *,
    reference: datetime,
    energy_slots: Sequence[Mapping[str, Any]],
    solar_slots: Sequence[Mapping[str, Any]],
    plans: Sequence[Mapping[str, Any]],
    start_soc_percent: float,
    capacity_kwh: float,
    price_by_start: Mapping[str, Mapping[str, Any]],
    settings: Mapping[str, Any],
) -> str:
    """Hash the exact policy inputs used by one background computation."""
    return _stable_digest(
        {
            "runtime": RUNTIME_VERSION,
            "policy": PLANNER_POLICY_VERSION,
            "cycle": planner_cycle_id(reference),
            "energy_slots": list(energy_slots),
            "solar_slots": list(solar_slots),
            "plans": list(plans),
            "soc": float(start_soc_percent),
            "capacity_kwh": float(capacity_kwh),
            "price_by_start": dict(price_by_start),
            "settings": dict(settings),
        }
    )


def _timeline_points(snapshot: Mapping[str, Any]) -> list[list[float | int]]:
    points: list[list[float | int]] = []
    for row in snapshot.get("native_slots") or []:
        try:
            parsed = datetime.fromisoformat(str(row.get("start")).replace("Z", "+00:00"))
            soc = float(row.get("end_soc_percent"))
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        points.append([int(parsed.timestamp() * 1000), round(soc, 4)])
    return points


def compute_automatic_planner_snapshot(
    *,
    reference: datetime,
    energy_records: list[dict[str, Any]],
    energy_profile: str,
    local_timezone: Any,
    solar_slots: Sequence[Mapping[str, Any]],
    plans: Sequence[Mapping[str, Any]],
    start_soc_percent: float,
    capacity_kwh: float,
    price_by_start: Mapping[str, Mapping[str, Any]],
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one immutable-ready R5 planner snapshot outside the HA event loop."""
    forecast = EnergyBaselineForecast(
        energy_records,
        local_timezone=local_timezone,
    ).build(energy_profile, now=_as_utc(reference))
    energy_slots = [
        {
            "start": slot.start.isoformat(),
            "end": slot.end.isoformat(),
            "home_kwh": slot.energy_kwh,
        }
        for slot in forecast
    ]

    result = build_automatic_plan(
        energy_slots=energy_slots,
        solar_slots=solar_slots,
        plans=plans,
        start_soc_percent=float(start_soc_percent),
        capacity_kwh=float(capacity_kwh),
        price_by_start=price_by_start,
        software_reserve_percent=float(settings["software_reserve_percent"]),
        max_charge_power_w=float(settings["max_charge_power_w"]),
        max_discharge_power_w=float(settings["max_discharge_power_w"]),
        minimum_trade_margin_eur_per_kwh=float(
            settings["minimum_trade_margin_eur_per_kwh"]
        ),
        peak_sale_threshold_eur_per_kwh=float(
            settings["peak_sale_threshold_eur_per_kwh"]
        ),
    )
    result["runtime_version"] = RUNTIME_VERSION
    result["planner_policy_version"] = PLANNER_POLICY_VERSION
    result["planner_cycle_id"] = planner_cycle_id(reference)
    result["planner_reference"] = _as_utc(reference).isoformat()
    result["planner_input_signature"] = planner_input_signature(
        reference=reference,
        energy_slots=energy_slots,
        solar_slots=solar_slots,
        plans=plans,
        start_soc_percent=start_soc_percent,
        capacity_kwh=capacity_kwh,
        price_by_start=price_by_start,
        settings=settings,
    )
    result["timeline_points"] = _timeline_points(result)
    return result
