"""Alpha36 best-of-both compatibility adapter from DOEMS transport rows.

The DOEMS source of truth remains 288 native 15-minute slots. This adapter only
presents the proven rolling 72 x 60-minute compatibility view to the Alpha36 best-of-both decision core. It never rounds a :15/:30/:45 window back to a clock hour.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .ems_alpha36.energy_need import build_energy_need_analysis
from .ems_alpha36.planner_preview import build_planner_preview
from .ems_alpha36.planner_72h import build_72h_plan_preview
from .ems_settings import EMSSettings

SOURCE_TAG = "alpha39_planstore_commitment_replay_v1"
ECONOMIC_POLICY = "alpha80_cheapest_energy_safety_v1"
SAFETY_AUTHORITY = "doems_alpha38_split_reserve_safety_reachability_v1"
EXECUTION_BUFFER_PERCENT = 2.0

def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)

def planner_reference(input_result: dict[str, Any], fallback: datetime | None = None) -> datetime:
    contract = input_result.get("time_contract") or {}
    for key in ("window_start", "planner_start", "start"):
        parsed = _aware(contract.get(key))
        if parsed is not None:
            return parsed
    parsed = _aware(input_result.get("planner_start")) or _aware(input_result.get("window_start"))
    if parsed is not None:
        return parsed
    if fallback is not None:
        if fallback.tzinfo is None:
            raise ValueError("fallback reference must be timezone-aware")
        return fallback.astimezone(timezone.utc)
    raise ValueError("planner window start missing")

def forecast_from_input(input_result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = input_result.get("rows")
    if not isinstance(rows, list) or len(rows) != 72:
        raise ValueError("alpha36 adapter requires exactly 72 transport rows")
    forecast: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"planner row {index} is invalid")
        start = _aware(raw.get("start"))
        if start is None:
            raise ValueError(f"planner row {index} has invalid timestamp")
        source = raw.get("price_source")
        forecast.append({
            "time": start.isoformat(),
            "home_consumption_kwh": raw.get("home_kwh"),
            "solar_kwh": raw.get("solar_kwh"),
            "solar_forecast_valid": bool(raw.get("solar_valid")),
            "price": raw.get("import_price"),
            "import_price": raw.get("import_price"),
            "export_price": raw.get("export_price"),
            "price_source": source,
            "import_price_source": raw.get("import_price_source") or source,
            "export_price_source": raw.get("export_price_source") or source,
            "adapter_row_index": index,
        })
    return forecast


def _with_transport_observability(
    plan72: dict[str, Any],
    input_result: dict[str, Any],
) -> dict[str, Any]:
    """Add DOEMS transport diagnostics without changing Anker planner decisions."""
    result = deepcopy(plan72)
    plan = result.get("auto_plan_72h_plan") or []
    rows = input_result.get("rows") or []

    coverage = sum(
        1
        for row in rows
        if isinstance(row, dict) and row.get("solar_valid") is True
    )
    missing = max(0, 72 - coverage)
    complete = coverage == 72
    coverage_percent = round(coverage / 72 * 100.0, 1)

    next_usable = plan[0].get("next_usable_solar") if plan else None
    next_usable_dt = _aware(next_usable)
    first_row_dt = _aware(rows[0].get("start")) if rows and isinstance(rows[0], dict) else None
    hours_until_next = (
        round(max(0.0, (next_usable_dt - first_row_dt).total_seconds() / 3600.0), 2)
        if next_usable_dt is not None and first_row_dt is not None
        else None
    )
    last_usable = next(
        (
            item.get("next_usable_solar")
            for item in reversed(plan)
            if isinstance(item, dict) and item.get("next_usable_solar") is not None
        ),
        None,
    )
    hours_after_last = sum(
        1
        for item in plan
        if isinstance(item, dict) and not item.get("solar_horizon_complete", False)
    )
    limited_by_end = bool(plan and complete and hours_after_last > 0)
    next_available = next_usable is not None

    if coverage == 0 or not plan:
        status = "no_data"
        reason = "Geen bruikbare solarforecast beschikbaar voor Plan72."
    elif not complete:
        status = "limited"
        reason = (
            f"Solarforecast dekt {coverage}/72 uur; "
            f"{missing} uur ontbreekt."
        )
    elif not next_available:
        status = "limited"
        reason = (
            "Solarforecast dekt 72 uur, maar vanaf Plan72-start is binnen "
            "de huidige horizon geen bruikbaar zonneblok gevonden."
        )
    else:
        status = "ready"
        reason = (
            "Solarforecast dekt 72 uur en het volgende bruikbare zonneblok "
            "is vanaf Plan72-start beschikbaar."
        )

    result.update(
        {
            "auto_plan_72h_solar_horizon_status": status,
            "auto_plan_72h_solar_horizon_reason": reason,
            "auto_plan_72h_solar_forecast_coverage_hours": coverage,
            "auto_plan_72h_solar_forecast_missing_hours": missing,
            "auto_plan_72h_solar_forecast_coverage_percent": coverage_percent,
            "auto_plan_72h_solar_forecast_complete": complete,
            "auto_plan_72h_next_usable_solar_available": next_available,
            "auto_plan_72h_next_usable_solar": next_usable,
            "auto_plan_72h_hours_until_next_usable_solar": hours_until_next,
            "auto_plan_72h_last_usable_solar": last_usable,
            "auto_plan_72h_hours_after_last_usable_solar": hours_after_last,
            "auto_plan_72h_lookahead_limited_by_plan_end": limited_by_end,
        }
    )
    return result

def run_energy_need(*, input_result: dict[str, Any], settings: EMSSettings, soc_percent: float | None, now: datetime | None = None) -> dict[str, Any]:
    reference = planner_reference(input_result, now)
    return build_energy_need_analysis(
        forecast_from_input(input_result),
        soc_percent,
        settings.software_reserve_percent,
        now=reference,
    )

def run_preview(*, input_result: dict[str, Any], settings: EMSSettings, energy_need: dict[str, Any], soc_percent: float | None, now: datetime | None = None) -> dict[str, Any]:
    reference = planner_reference(input_result, now)
    return build_planner_preview(
        forecast_from_input(input_result),
        energy_need,
        soc_percent,
        settings.charge_efficiency_percent,
        settings.discharge_efficiency_percent,
        settings.minimum_trade_margin_eur_per_kwh,
        max_charge_power_w=settings.max_charge_power_w,
        max_discharge_power_w=settings.max_discharge_power_w,
        now=reference,
    )

def run_plan72(*, input_result: dict[str, Any], settings: EMSSettings, energy_need: dict[str, Any], planner_preview: dict[str, Any], soc_percent: float | None, now: datetime | None = None, commitments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    reference = planner_reference(input_result, now)
    raw = build_72h_plan_preview(
        forecast_from_input(input_result),
        energy_need,
        planner_preview,
        soc_percent,
        settings.charge_efficiency_percent,
        settings.discharge_efficiency_percent,
        execution_buffer_percent=EXECUTION_BUFFER_PERCENT,
        max_charge_power_w=settings.max_charge_power_w,
        max_discharge_power_w=settings.max_discharge_power_w,
        now=reference,
        commitments=commitments or [],
    )
    return _with_transport_observability(raw, input_result)

def run_ems_chain(*, input_result: dict[str, Any], settings: EMSSettings, soc_percent: float | None, now: datetime | None = None, commitments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    need = run_energy_need(input_result=input_result, settings=settings, soc_percent=soc_percent, now=now)
    preview = run_preview(input_result=input_result, settings=settings, energy_need=need, soc_percent=soc_percent, now=now)
    plan72 = run_plan72(input_result=input_result, settings=settings, energy_need=need, planner_preview=preview, soc_percent=soc_percent, now=now, commitments=commitments or [])
    return {
        "energy_need": deepcopy(need),
        "planner_preview": deepcopy(preview),
        "plan72": deepcopy(plan72),
        "ems_policy_source": SOURCE_TAG,
        "adapter_contract": "alpha41_288_to_72+alpha80_cheapest_energy+alpha38_split_reserve_safety+alpha39_commitment_replay_v1",
        "economic_policy": ECONOMIC_POLICY,
        "safety_authority": SAFETY_AUTHORITY,
        "startup_delay_runtime_gate_active": False,
        "planner_runtime_active": True,
        "plan_store_write": True,
        "scheduler_invoked": True,
        "service_calls_performed": False,
        "physical_execution_authority": False,
    }
