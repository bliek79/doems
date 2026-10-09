"""Cached worker helpers for the DOEMS Automatic and Combined Planners."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import time
from collections.abc import Callable
from threading import Event
from typing import Any, Mapping, Sequence

from .energy_forecast import EnergyBaselineForecast
from .planner_diagnostics import PlannerDiagnostics
from .automatic_combined_planner_model import (
    PlannerComputeBudgetExceeded,
    PlannerComputeCancelled,
    build_planner_bundle,
)

RUNTIME_VERSION = "automatic_combined_sequential_exact_safety_v4"
PLANNER_POLICY_VERSION = "manual_priority_parity_v1"
PLANNER_COMPUTE_BUDGET_SECONDS = 20.0


def make_planner_work_guard(
    stop: Event, *, seconds: float = PLANNER_COMPUTE_BUDGET_SECONDS,
) -> Callable[[], None]:
    """One cooperative deadline for the two serial native 288-slot plans."""
    deadline = time.monotonic() + seconds

    def check() -> None:
        if stop.is_set():
            raise PlannerComputeCancelled("planner_generation_superseded")
        if time.monotonic() >= deadline:
            raise PlannerComputeBudgetExceeded("planner_compute_budget_exceeded")

    return check



def _as_utc(reference: datetime) -> datetime:
    if reference.tzinfo is None:
        return reference.replace(tzinfo=timezone.utc)
    return reference.astimezone(timezone.utc)


def planner_cycle_id(reference: datetime) -> str:
    reference_utc = _as_utc(reference)
    minute = (reference_utc.minute // 15) * 15
    return reference_utc.replace(
        minute=minute, second=0, microsecond=0
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
            parsed = datetime.fromisoformat(
                str(row.get("start")).replace("Z", "+00:00")
            )
            soc = float(row.get("end_soc_percent"))
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        points.append([int(parsed.timestamp() * 1000), round(soc, 4)])
    return points


def compute_planner_bundle(
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
    check_work: Callable[[], None] | None = None,
    stage: str = "both",
    diagnostics: PlannerDiagnostics | None = None,
    automatic_snapshot: Mapping[str, Any] | None = None,
    prebuilt_energy_slots: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute the selected stage in one executor, never both for live runs.

    The legacy both-stage API remains available for regression tests. The
    sequential manager requests Automatic first and later Combined from the
    exact same prepared 288 quarter inputs, so manual-only changes never
    re-run the Automatic policy or its Energy forecast.
    """
    if diagnostics is not None:
        diagnostics.enter("energy_forecast_build")
        diagnostics.context.update({"energy_record_count": len(energy_records), "energy_profile": energy_profile, "solar_slot_count": len(solar_slots), "price_slot_count": len(price_by_start), "prebuilt_energy": prebuilt_energy_slots is not None})
    if check_work is not None:
        check_work()
    if prebuilt_energy_slots is None:
        forecast = EnergyBaselineForecast(
            energy_records,
            local_timezone=local_timezone,
        ).build(energy_profile, now=_as_utc(reference))
        if check_work is not None:
            check_work()
        energy_slots = [
            {
                "start": slot.start.isoformat(),
                "end": slot.end.isoformat(),
                "home_kwh": slot.energy_kwh,
            }
            for slot in forecast
        ]
    else:
        energy_slots = [dict(row) for row in prebuilt_energy_slots]

    bundle = build_planner_bundle(
        energy_slots=energy_slots,
        solar_slots=solar_slots,
        plans=plans,
        start_soc_percent=float(start_soc_percent),
        capacity_kwh=float(capacity_kwh),
        price_by_start=price_by_start,
        software_reserve_percent=float(
            settings["software_reserve_percent"]
        ),
        max_charge_power_w=float(settings["max_charge_power_w"]),
        max_discharge_power_w=float(
            settings["max_discharge_power_w"]
        ),
        minimum_trade_margin_eur_per_kwh=float(
            settings["minimum_trade_margin_eur_per_kwh"]
        ),
        check_work=check_work,
        stage=stage,
        automatic_snapshot=automatic_snapshot,
        diagnostics=diagnostics,
    )

    if check_work is not None:
        check_work()
    if diagnostics is not None:
        diagnostics.enter("publication_preparation")
    signature = planner_input_signature(
        reference=reference,
        energy_slots=energy_slots,
        solar_slots=solar_slots,
        plans=plans,
        start_soc_percent=start_soc_percent,
        capacity_kwh=capacity_kwh,
        price_by_start=price_by_start,
        settings=settings,
    )
    for key in ("automatic", "combined"):
        snapshot = bundle.get(key)
        if not isinstance(snapshot, dict):
            continue
        snapshot["runtime_version"] = RUNTIME_VERSION
        snapshot["planner_policy_version"] = PLANNER_POLICY_VERSION
        snapshot["planner_cycle_id"] = planner_cycle_id(reference)
        snapshot["planner_reference"] = _as_utc(reference).isoformat()
        snapshot["planner_input_signature"] = signature
        snapshot["timeline_points"] = _timeline_points(snapshot)

    if check_work is not None:
        check_work()
    bundle["runtime_version"] = RUNTIME_VERSION
    bundle["planner_policy_version"] = PLANNER_POLICY_VERSION
    bundle["planner_cycle_id"] = planner_cycle_id(reference)
    bundle["planner_reference"] = _as_utc(reference).isoformat()
    bundle["planner_input_signature"] = signature
    if stage == "automatic":
        bundle["_prepared_energy_slots"] = energy_slots
    return bundle

