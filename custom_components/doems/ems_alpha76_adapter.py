"""Thin Alpha41 compatibility adapter from DOEMS transport rows to Alpha76.

The DOEMS source of truth remains 288 native 15-minute slots. This adapter only
presents the proven rolling 72 x 60-minute compatibility view to the frozen
Alpha76 decision core. It never rounds a :15/:30/:45 window back to a clock hour.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .ems_alpha76.energy_need import build_energy_need_analysis
from .ems_alpha76.planner_preview import build_planner_preview
from .ems_alpha76.planner_72h import build_72h_plan_preview
from .ems_settings import EMSSettings

SOURCE_TAG = "0.0.1-alpha.76"
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
        raise ValueError("alpha76 adapter requires exactly 72 transport rows")
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
            "price": raw.get("import_price"),
            "import_price": raw.get("import_price"),
            "export_price": raw.get("export_price"),
            "price_source": source,
            "import_price_source": raw.get("import_price_source") or source,
            "export_price_source": raw.get("export_price_source") or source,
            "adapter_row_index": index,
        })
    return forecast

def run_energy_need(*, input_result: dict[str, Any], settings: EMSSettings, soc_percent: float | None, now: datetime | None = None) -> dict[str, Any]:
    reference = planner_reference(input_result, now)
    return build_energy_need_analysis(
        forecast_from_input(input_result),
        soc_percent,
        settings.software_reserve_percent,
        battery_capacity_kwh=settings.battery_capacity_kwh,
        technical_min_soc_percent=settings.technical_min_soc_percent,
        max_soc_percent=settings.max_soc_percent,
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
        battery_capacity_kwh=settings.battery_capacity_kwh,
        technical_min_soc_percent=settings.technical_min_soc_percent,
        max_soc_percent=settings.max_soc_percent,
        now=reference,
    )

def run_plan72(*, input_result: dict[str, Any], settings: EMSSettings, energy_need: dict[str, Any], planner_preview: dict[str, Any], soc_percent: float | None, now: datetime | None = None) -> dict[str, Any]:
    reference = planner_reference(input_result, now)
    return build_72h_plan_preview(
        forecast_from_input(input_result),
        energy_need,
        planner_preview,
        soc_percent,
        settings.charge_efficiency_percent,
        settings.discharge_efficiency_percent,
        execution_buffer_percent=EXECUTION_BUFFER_PERCENT,
        max_charge_power_w=settings.max_charge_power_w,
        max_discharge_power_w=settings.max_discharge_power_w,
        battery_capacity_kwh=settings.battery_capacity_kwh,
        technical_min_soc_percent=settings.technical_min_soc_percent,
        max_soc_percent=settings.max_soc_percent,
        now=reference,
    )

def run_ems_chain(*, input_result: dict[str, Any], settings: EMSSettings, soc_percent: float | None, now: datetime | None = None) -> dict[str, Any]:
    need = run_energy_need(input_result=input_result, settings=settings, soc_percent=soc_percent, now=now)
    preview = run_preview(input_result=input_result, settings=settings, energy_need=need, soc_percent=soc_percent, now=now)
    plan72 = run_plan72(input_result=input_result, settings=settings, energy_need=need, planner_preview=preview, soc_percent=soc_percent, now=now)
    return {
        "energy_need": deepcopy(need),
        "planner_preview": deepcopy(preview),
        "plan72": deepcopy(plan72),
        "ems_policy_source": SOURCE_TAG,
        "adapter_contract": "alpha41_288_to_72",
        "startup_delay_runtime_gate_active": False,
        "planner_runtime_active": True,
        "plan_store_write": True,
        "scheduler_invoked": True,
        "service_calls_performed": False,
        "physical_execution_authority": False,
    }
