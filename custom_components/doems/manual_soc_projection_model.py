"""Pure native-quarter manual SOC projection for DOEMS R3."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

FORECAST_SLOTS = 288
SLOT_SECONDS = 15 * 60
HORIZON_HOURS = 72
MIN_SOC_PERCENT = 5.0
MAX_SOC_PERCENT = 100.0
CHARGE_EFFICIENCY = 0.92
DISCHARGE_EFFICIENCY = 0.92
MAX_PROJECTION_POWER_W = 3500.0

_ACTIVE_MANUAL_LIFECYCLES = {"pending", "actief"}


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _nonnegative_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0.0 else None


def _bounded_soc(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0.0 <= number <= 100.0 else None


def _manual_commitments(
    plans: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    commitments: list[dict[str, Any]] = []
    blockers: list[str] = []

    for raw in plans:
        lifecycle = str(raw.get("lifecycle_status") or "").lower()
        origin = str(raw.get("origin") or "manual")
        action = str(raw.get("action") or "geen")
        if origin != "manual" or lifecycle not in _ACTIVE_MANUAL_LIFECYCLES:
            continue
        if action not in {"laden", "ontladen"}:
            blockers.append(f"manual_plan_{raw.get('slot')}_action_invalid")
            continue

        start = _aware_datetime(raw.get("start_time"))
        runtime_h = _nonnegative_float(raw.get("max_runtime_h"))
        power_w = _nonnegative_float(raw.get("power_w"))
        target_soc = _bounded_soc(raw.get("target_soc"))
        if start is None:
            blockers.append(f"manual_plan_{raw.get('slot')}_start_time_invalid")
            continue
        if runtime_h is None or not 0.5 <= runtime_h <= 12.0:
            blockers.append(f"manual_plan_{raw.get('slot')}_runtime_invalid")
            continue
        if power_w is None or not 100.0 <= power_w <= MAX_PROJECTION_POWER_W:
            blockers.append(f"manual_plan_{raw.get('slot')}_power_invalid")
            continue
        if target_soc is None or not MIN_SOC_PERCENT <= target_soc <= MAX_SOC_PERCENT:
            blockers.append(f"manual_plan_{raw.get('slot')}_target_soc_invalid")
            continue

        commitments.append(
            {
                "slot": int(raw.get("slot") or 0),
                "action": action,
                "start": start,
                "end": start + timedelta(hours=runtime_h),
                "power_w": power_w,
                "target_soc": target_soc,
                "lifecycle_status": lifecycle,
            }
        )

    commitments.sort(key=lambda item: (item["start"], item["slot"]))

    for index, current in enumerate(commitments):
        for other in commitments[index + 1 :]:
            if other["start"] >= current["end"]:
                break
            if other["start"] < current["end"] and other["end"] > current["start"]:
                blockers.append(
                    f"manual_plan_overlap:{current['slot']}:{other['slot']}"
                )

    return commitments, blockers


def _validate_time_axis(
    energy_slots: Sequence[Mapping[str, Any]],
    solar_slots: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    blockers: list[str] = []
    if len(energy_slots) != FORECAST_SLOTS:
        blockers.append("energy_slot_count_invalid")
    if len(solar_slots) != FORECAST_SLOTS:
        blockers.append("solar_slot_count_invalid")
    if blockers:
        return [], blockers

    solar_by_start: dict[datetime, float] = {}
    for raw in solar_slots:
        start = _aware_datetime(raw.get("start"))
        solar_kwh = _nonnegative_float(raw.get("solar_kwh"))
        if start is None or solar_kwh is None:
            blockers.append("solar_slot_invalid")
            continue
        if start in solar_by_start:
            blockers.append("solar_slot_duplicate")
            continue
        solar_by_start[start] = solar_kwh

    normalized: list[dict[str, Any]] = []
    previous_end: datetime | None = None
    for index, raw in enumerate(energy_slots):
        start = _aware_datetime(raw.get("start"))
        end = _aware_datetime(raw.get("end"))
        home_kwh = _nonnegative_float(raw.get("home_kwh"))
        if start is None or end is None or home_kwh is None:
            blockers.append(f"energy_slot_{index}_invalid")
            continue
        if int((end - start).total_seconds()) != SLOT_SECONDS:
            blockers.append(f"energy_slot_{index}_duration_invalid")
        if previous_end is not None and start != previous_end:
            blockers.append(f"energy_slot_{index}_not_contiguous")
        previous_end = end
        if start not in solar_by_start:
            blockers.append(f"solar_alignment_missing:{start.isoformat()}")
            solar_kwh = 0.0
        else:
            solar_kwh = solar_by_start[start]
        normalized.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "home_kwh": home_kwh,
                "solar_kwh": solar_kwh,
            }
        )

    if len(normalized) == FORECAST_SLOTS:
        expected_horizon = normalized[-1]["end"] - normalized[0]["start"]
        if expected_horizon != timedelta(hours=HORIZON_HOURS):
            blockers.append("forecast_horizon_invalid")

    return normalized, blockers


def _slot_price(
    price_by_start: Mapping[str, Mapping[str, Any]] | None,
    start: datetime,
) -> dict[str, Any]:
    if not price_by_start:
        return {
            "price": None,
            "import_price": None,
            "export_price": None,
            "price_source": None,
            "price_kind": None,
        }
    raw = price_by_start.get(start.isoformat())
    if not isinstance(raw, Mapping):
        return {
            "price": None,
            "import_price": None,
            "export_price": None,
            "price_source": None,
            "price_kind": None,
        }
    import_price = raw.get("import_all_in")
    export_price = raw.get("export_all_in")
    kind = str(raw.get("kind") or "")
    try:
        import_value = float(import_price) if import_price is not None else None
    except (TypeError, ValueError):
        import_value = None
    try:
        export_value = float(export_price) if export_price is not None else None
    except (TypeError, ValueError):
        export_value = None
    return {
        "price": import_value,
        "import_price": import_value,
        "export_price": export_value,
        "price_source": (
            "known" if kind.startswith("known_") else "forecast" if kind else None
        ),
        "price_kind": kind or None,
    }


def _aggregate_clock_hours(native_slots: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[datetime, list[Mapping[str, Any]]] = defaultdict(list)
    for slot in native_slots:
        start = _aware_datetime(slot.get("start"))
        if start is None:
            continue
        bucket = start.replace(minute=0, second=0, microsecond=0)
        groups[bucket].append(slot)

    result: list[dict[str, Any]] = []
    sum_fields = (
        "solar_kwh",
        "home_consumption_kwh",
        "solar_to_home_kwh",
        "charge_from_solar_kwh",
        "discharge_to_home_kwh",
        "grid_to_home_kwh",
        "solar_to_grid_kwh",
        "manual_charge_kwh",
        "manual_discharge_kwh",
    )
    for bucket in sorted(groups):
        rows = groups[bucket]
        item: dict[str, Any] = {
            "time": bucket.isoformat(),
            "slot_count": len(rows),
            "soc_start": rows[0].get("start_soc_percent"),
            "soc_end": rows[-1].get("end_soc_percent"),
            "manual_slots": sorted(
                {
                    int(slot)
                    for row in rows
                    for slot in (row.get("manual_slots") or [])
                    if int(slot) > 0
                }
            ),
            "replanned": True,
            "manual_projection_only": True,
        }
        for field in sum_fields:
            item[field] = round(
                sum(float(row.get(field) or 0.0) for row in rows),
                6,
            )

        import_values = [
            float(row["import_price"])
            for row in rows
            if row.get("import_price") is not None
        ]
        export_values = [
            float(row["export_price"])
            for row in rows
            if row.get("export_price") is not None
        ]
        sources = [row.get("price_source") for row in rows if row.get("price_source")]
        if import_values:
            item["price"] = round(sum(import_values) / len(import_values), 8)
            item["import_price"] = item["price"]
        if export_values:
            item["export_price"] = round(sum(export_values) / len(export_values), 8)
        if sources:
            item["price_source"] = "known" if all(v == "known" for v in sources) else "forecast"

        result.append(item)
    return result


def project_manual_soc(
    *,
    energy_slots: Sequence[Mapping[str, Any]],
    solar_slots: Sequence[Mapping[str, Any]],
    plans: Sequence[Mapping[str, Any]],
    start_soc_percent: float,
    capacity_kwh: float,
    price_by_start: Mapping[str, Mapping[str, Any]] | None = None,
    charge_efficiency: float = CHARGE_EFFICIENCY,
    discharge_efficiency: float = DISCHARGE_EFFICIENCY,
    minimum_soc_percent: float = MIN_SOC_PERCENT,
    max_projection_power_w: float = MAX_PROJECTION_POWER_W,
) -> dict[str, Any]:
    """Project the 72-hour battery SOC with manual plans as hard commitments."""
    blockers: list[str] = []
    if not 0.0 <= float(start_soc_percent) <= 100.0:
        blockers.append("start_soc_invalid")
    if float(capacity_kwh) <= 0.0:
        blockers.append("capacity_invalid")
    if not 0.5 <= float(charge_efficiency) <= 1.0:
        blockers.append("charge_efficiency_invalid")
    if not 0.5 <= float(discharge_efficiency) <= 1.0:
        blockers.append("discharge_efficiency_invalid")

    axis, axis_blockers = _validate_time_axis(energy_slots, solar_slots)
    blockers.extend(axis_blockers)
    commitments, commitment_blockers = _manual_commitments(plans)
    blockers.extend(commitment_blockers)

    if blockers:
        return {
            "status": "blocked",
            "valid": False,
            "blockers": sorted(set(blockers)),
            "native_slots": [],
            "hourly_plan": [],
            "manual_commitment_count": len(commitments),
            "manual_commitment_slots": [item["slot"] for item in commitments],
            "start_soc_percent": None,
            "end_soc_percent": None,
            "min_soc_percent": minimum_soc_percent,
            "max_soc_percent": MAX_SOC_PERCENT,
            "capacity_kwh": float(capacity_kwh) if float(capacity_kwh) > 0 else None,
            "charge_efficiency_percent": round(float(charge_efficiency) * 100.0, 1),
            "discharge_efficiency_percent": round(float(discharge_efficiency) * 100.0, 1),
            "physical_execution_authority": False,
            "automatic_planner_active": False,
            "scheduler_active": False,
            "mode": "manual_projection_only",
        }

    soc = min(MAX_SOC_PERCENT, max(float(minimum_soc_percent), float(start_soc_percent)))
    native: list[dict[str, Any]] = []
    max_power_w = min(float(max_projection_power_w), MAX_PROJECTION_POWER_W)

    for slot in axis:
        start = slot["start"]
        end = slot["end"]
        active: list[tuple[dict[str, Any], float]] = []
        for plan in commitments:
            overlap = max(
                0.0,
                (min(end, plan["end"]) - max(start, plan["start"])).total_seconds(),
            )
            if overlap > 0.0:
                active.append((plan, overlap))

        manual_overlap_seconds = sum(overlap for _, overlap in active)
        automatic_seconds = max(0.0, SLOT_SECONDS - manual_overlap_seconds)
        automatic_fraction = automatic_seconds / SLOT_SECONDS

        home_total = float(slot["home_kwh"])
        solar_total = float(slot["solar_kwh"])
        home = home_total * automatic_fraction
        solar = solar_total * automatic_fraction

        start_soc = soc
        solar_to_home = min(home, solar)
        solar_surplus = max(0.0, solar - solar_to_home)
        home_deficit = max(0.0, home - solar_to_home)

        max_auto_energy = max_power_w / 1000.0 * automatic_seconds / 3600.0
        free_input = max(
            0.0,
            (MAX_SOC_PERCENT - soc)
            / 100.0
            * float(capacity_kwh)
            / float(charge_efficiency),
        )
        solar_charge = min(solar_surplus, free_input, max_auto_energy)
        soc += (
            solar_charge
            * float(charge_efficiency)
            / float(capacity_kwh)
            * 100.0
        )

        available_output = max(
            0.0,
            (soc - float(minimum_soc_percent))
            / 100.0
            * float(capacity_kwh)
            * float(discharge_efficiency),
        )
        home_discharge = min(home_deficit, available_output, max_auto_energy)
        soc -= (
            home_discharge
            / float(discharge_efficiency)
            / float(capacity_kwh)
            * 100.0
        )

        manual_charge = 0.0
        manual_discharge = 0.0
        manual_slots: list[int] = []
        for plan, overlap_seconds in active:
            requested = (
                min(plan["power_w"], max_power_w)
                / 1000.0
                * overlap_seconds
                / 3600.0
            )
            target = min(
                MAX_SOC_PERCENT,
                max(float(minimum_soc_percent), float(plan["target_soc"])),
            )
            if plan["action"] == "laden":
                target_input = max(
                    0.0,
                    (target - soc)
                    / 100.0
                    * float(capacity_kwh)
                    / float(charge_efficiency),
                )
                actual = min(requested, target_input)
                soc += (
                    actual
                    * float(charge_efficiency)
                    / float(capacity_kwh)
                    * 100.0
                )
                manual_charge += actual
            else:
                target_output = max(
                    0.0,
                    (soc - target)
                    / 100.0
                    * float(capacity_kwh)
                    * float(discharge_efficiency),
                )
                actual = min(requested, target_output)
                soc -= (
                    actual
                    / float(discharge_efficiency)
                    / float(capacity_kwh)
                    * 100.0
                )
                manual_discharge += actual
            manual_slots.append(plan["slot"])

        soc = min(MAX_SOC_PERCENT, max(float(minimum_soc_percent), soc))
        prices = _slot_price(price_by_start, start)
        native.append(
            {
                "index": slot["index"],
                "start": start.isoformat(),
                "end": end.isoformat(),
                "home_kwh": round(home_total, 6),
                "solar_kwh": round(solar_total, 6),
                "home_consumption_kwh": round(home_total, 6),
                "start_soc_percent": round(start_soc, 4),
                "end_soc_percent": round(soc, 4),
                "soc_end": round(soc, 4),
                "solar_to_home_kwh": round(solar_to_home, 6),
                "charge_from_solar_kwh": round(solar_charge, 6),
                "discharge_to_home_kwh": round(home_discharge, 6),
                "grid_to_home_kwh": round(max(0.0, home_deficit - home_discharge), 6),
                "solar_to_grid_kwh": round(max(0.0, solar_surplus - solar_charge), 6),
                "manual_charge_kwh": round(manual_charge, 6),
                "manual_discharge_kwh": round(manual_discharge, 6),
                "manual_slots": sorted(set(manual_slots)),
                "manual_overlap_seconds": round(manual_overlap_seconds, 3),
                "automatic_fraction": round(automatic_fraction, 6),
                "replanned": True,
                **prices,
            }
        )

    hourly = _aggregate_clock_hours(native)
    soc_values = [float(row["end_soc_percent"]) for row in native]
    return {
        "status": "ready",
        "valid": True,
        "blockers": [],
        "native_slots": native,
        "hourly_plan": hourly,
        "native_slot_count": len(native),
        "clock_hour_bucket_count": len(hourly),
        "manual_commitment_count": len(commitments),
        "manual_commitment_slots": [item["slot"] for item in commitments],
        "start": native[0]["start"] if native else None,
        "end": native[-1]["end"] if native else None,
        "start_soc_percent": round(float(start_soc_percent), 4),
        "end_soc_percent": round(float(soc), 4),
        "projected_min_soc_percent": round(min(soc_values), 4) if soc_values else None,
        "projected_max_soc_percent": round(max(soc_values), 4) if soc_values else None,
        "min_soc_percent": float(minimum_soc_percent),
        "max_soc_percent": MAX_SOC_PERCENT,
        "capacity_kwh": round(float(capacity_kwh), 6),
        "charge_efficiency_percent": round(float(charge_efficiency) * 100.0, 1),
        "discharge_efficiency_percent": round(float(discharge_efficiency) * 100.0, 1),
        "max_projection_power_w": max_power_w,
        "physical_execution_authority": False,
        "automatic_planner_active": False,
        "scheduler_active": False,
        "mode": "manual_projection_only",
    }
