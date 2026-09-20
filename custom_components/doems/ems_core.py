"""Pure native-15-minute G6 EMS calculation core.

The formulas are a resolution translation of the frozen Dummy OS EMS logic.
No Home Assistant entities, services or physical execution are used here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from .ems_settings import EMSSettings

SLOT_MINUTES = 15
SLOT_HOURS = 0.25
FORECAST_SLOTS = 288
USABLE_SOLAR_WINDOW_SLOTS = 8  # preserve the legacy two-hour confirmation window
EXECUTION_BUFFER_PERCENT = 2.0
MIN_ENERGY_KWH = 0.01


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value not in (None, ""):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _floor_quarter(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    return value.replace(
        minute=(value.minute // SLOT_MINUTES) * SLOT_MINUTES,
        second=0,
        microsecond=0,
    )


def _slot_fraction(slot_start: datetime, now_utc: datetime) -> float:
    current = _floor_quarter(now_utc)
    if slot_start != current:
        return 1.0
    elapsed_seconds = (now_utc - current).total_seconds()
    return max(0.0, min(1.0, 1.0 - elapsed_seconds / (SLOT_MINUTES * 60.0)))


def _normalize_slots(forecast: list[dict[str, Any]], now_utc: datetime) -> list[dict[str, Any]]:
    current = _floor_quarter(now_utc)
    rows: list[dict[str, Any]] = []
    for raw in forecast:
        start = _parse_time(raw.get("time"))
        if start is None or start < current:
            continue
        home = _as_float(raw.get("home_consumption_kwh"))
        solar = _as_float(raw.get("solar_kwh"))
        import_price = _as_float(raw.get("import_price"))
        if import_price is None:
            import_price = _as_float(raw.get("price"))
        export_price = _as_float(raw.get("export_price"))
        if export_price is None:
            export_price = import_price
        rows.append(
            {
                "time": start,
                "home_kwh": home,
                "solar_kwh": solar,
                "import_price": import_price,
                "export_price": export_price,
                "price_source": raw.get("price_source"),
            }
        )
    rows.sort(key=lambda item: item["time"])
    return rows[:FORECAST_SLOTS]


def _usable_solar(rows: list[dict[str, Any]], index: int) -> bool:
    end = index + USABLE_SOLAR_WINDOW_SLOTS
    if index < 0 or end > len(rows):
        return False
    for item in rows[index:end]:
        home = item["home_kwh"]
        solar = item["solar_kwh"]
        if home is None or solar is None or solar <= 0 or solar < home:
            return False
    return True


def _next_usable_solar_index(rows: list[dict[str, Any]], start: int) -> int | None:
    for index in range(start, len(rows)):
        if _usable_solar(rows, index):
            return index
    return None


def build_energy_need_analysis(
    forecast: list[dict[str, Any]],
    soc: float | None,
    settings: EMSSettings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Calculate need until the first confirmed two-hour usable-solar window."""
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = _normalize_slots(forecast, now_utc)
    usable_index = _next_usable_solar_index(rows, 0)

    reserve_percent = max(0.0, min(30.0, settings.software_reserve_percent))
    reserve_kwh = settings.battery_capacity_kwh * reserve_percent / 100.0

    missing_home = False
    missing_solar = False
    net_need_kwh = 0.0
    contributing_hours = 0.0

    for index, row in enumerate(rows):
        if usable_index is not None and index >= usable_index:
            break
        home = row["home_kwh"]
        solar = row["solar_kwh"]
        if home is None:
            missing_home = True
            continue
        if solar is None:
            missing_solar = True
            solar = 0.0
        fraction = _slot_fraction(row["time"], now_utc)
        net_need_kwh += max(home - solar, 0.0) * fraction
        contributing_hours += SLOT_HOURS * fraction

    available_battery_kwh: float | None = None
    if soc is not None:
        bounded_soc = min(float(settings.max_soc_percent), float(soc))
        usable_soc = max(
            0.0, bounded_soc - float(settings.technical_min_soc_percent)
        )
        available_battery_kwh = (
            settings.battery_capacity_kwh * usable_soc / 100.0
        )

    required_including_reserve = net_need_kwh + reserve_kwh
    additional_grid_charge_kwh: float | None = None
    tradable_battery_kwh: float | None = None
    if available_battery_kwh is not None:
        additional_grid_charge_kwh = max(
            required_including_reserve - available_battery_kwh, 0.0
        )
        tradable_battery_kwh = max(
            available_battery_kwh - required_including_reserve, 0.0
        )

    first_usable = rows[usable_index]["time"] if usable_index is not None else None
    valid = (
        first_usable is not None
        and not missing_home
        and not missing_solar
        and available_battery_kwh is not None
    )

    return {
        "energy_need_status": "ready" if valid else "waiting_for_complete_forecast",
        "energy_need_valid": valid,
        "energy_need_until_solar_kwh": round(net_need_kwh, 3),
        "energy_need_first_usable_solar": first_usable.isoformat() if first_usable else None,
        "energy_need_available_battery_kwh": (
            round(available_battery_kwh, 3) if available_battery_kwh is not None else None
        ),
        "energy_need_safety_reserve_percent": round(reserve_percent, 1),
        "energy_need_safety_reserve_kwh": round(reserve_kwh, 3),
        "energy_need_required_including_reserve_kwh": round(required_including_reserve, 3),
        "energy_need_additional_grid_charge_kwh": (
            round(additional_grid_charge_kwh, 3)
            if additional_grid_charge_kwh is not None
            else None
        ),
        "energy_need_tradable_battery_kwh": (
            round(tradable_battery_kwh, 3)
            if tradable_battery_kwh is not None
            else None
        ),
        "energy_need_contributing_hours": round(contributing_hours, 2),
        "energy_need_battery_capacity_kwh": settings.battery_capacity_kwh,
        "energy_need_min_soc_percent": settings.technical_min_soc_percent,
        "energy_need_max_soc_percent": settings.max_soc_percent,
        "energy_need_resolution_minutes": SLOT_MINUTES,
        "energy_need_usable_solar_confirmation_slots": USABLE_SOLAR_WINDOW_SLOTS,
        "energy_need_observational_only": True,
    }


def build_planner_preview(
    forecast: list[dict[str, Any]],
    energy_need: dict[str, Any],
    soc: float | None,
    settings: EMSSettings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolution-translated frozen planner preview, with settings injected."""
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    current_slot = _floor_quarter(now_utc)
    rows = _normalize_slots(forecast, now_utc)

    charge_eff = max(0.50, min(1.00, settings.charge_efficiency_percent / 100.0))
    discharge_eff = max(0.50, min(1.00, settings.discharge_efficiency_percent / 100.0))
    roundtrip_eff = charge_eff * discharge_eff
    min_margin = max(0.0, settings.minimum_trade_margin_eur_per_kwh)

    valid = bool(energy_need.get("energy_need_valid"))
    need_kwh = _as_float(energy_need.get("energy_need_until_solar_kwh")) or 0.0
    reserve_kwh = _as_float(energy_need.get("energy_need_safety_reserve_kwh")) or 0.0
    additional_kwh = _as_float(energy_need.get("energy_need_additional_grid_charge_kwh"))
    tradable_kwh = _as_float(energy_need.get("energy_need_tradable_battery_kwh"))
    first_usable = _parse_time(energy_need.get("energy_need_first_usable_solar"))

    required_min_soc = settings.technical_min_soc_percent + (
        (need_kwh + reserve_kwh) / settings.battery_capacity_kwh * 100.0
    )
    required_min_soc = max(
        float(settings.technical_min_soc_percent),
        min(float(settings.max_soc_percent), required_min_soc),
    )

    priced = [
        row
        for row in rows
        if row["import_price"] is not None and row["export_price"] is not None
    ]
    safety_candidates = [
        row for row in priced if first_usable is None or row["time"] < first_usable
    ]
    safety_candidates.sort(key=lambda item: (item["import_price"], item["time"]))

    remaining = max(additional_kwh or 0.0, 0.0)
    selected_slots: list[dict[str, Any]] = []
    for row in safety_candidates:
        if remaining <= MIN_ENERGY_KWH:
            break
        fraction = _slot_fraction(row["time"], now_utc)
        slot_input_kwh = (
            settings.max_charge_power_w / 1000.0 * SLOT_HOURS * fraction
        )
        capacity_kwh = slot_input_kwh * charge_eff
        allocated = min(remaining, capacity_kwh)
        if allocated <= 0:
            continue
        selected_slots.append(
            {
                "time": row["time"].isoformat(),
                "import_price": row["import_price"],
                "export_price": row["export_price"],
                "max_battery_energy_kwh": round(capacity_kwh, 3),
                "candidate_battery_energy_kwh": round(allocated, 3),
            }
        )
        remaining -= allocated

    best_trade: dict[str, Any] | None = None
    for index, charge_row in enumerate(priced):
        effective_charge_cost = charge_row["import_price"] / roundtrip_eff
        for discharge_row in priced[index + 1 :]:
            net_margin = discharge_row["export_price"] - effective_charge_cost
            if best_trade is None or net_margin > best_trade["net_margin"]:
                best_trade = {
                    "charge_time": charge_row["time"],
                    "charge_price": charge_row["import_price"],
                    "discharge_time": discharge_row["time"],
                    "discharge_price": discharge_row["export_price"],
                    "effective_charge_cost": effective_charge_cost,
                    "net_margin": net_margin,
                }

    trade_profitable = bool(
        best_trade is not None and best_trade["net_margin"] >= min_margin
    )
    free_capacity_kwh = None
    if soc is not None:
        free_capacity_kwh = (
            settings.battery_capacity_kwh
            * max(0.0, settings.max_soc_percent - float(soc))
            / 100.0
        )

    safety_charge_needed = bool(
        valid and additional_kwh is not None and additional_kwh > MIN_ENERGY_KWH
    )
    discharge_possible = bool(
        valid
        and tradable_kwh is not None
        and tradable_kwh > MIN_ENERGY_KWH
        and soc is not None
        and float(soc) > required_min_soc
    )
    current_is_best_charge = bool(
        best_trade is not None and best_trade["charge_time"] == current_slot
    )
    current_is_best_discharge = bool(
        best_trade is not None and best_trade["discharge_time"] == current_slot
    )
    solar_charge_delay = bool(
        valid
        and not safety_charge_needed
        and first_usable is not None
        and first_usable > now_utc
    )

    if not valid:
        decision = "wachten"
    elif safety_charge_needed:
        decision = "veiligheidsladen"
    elif current_is_best_discharge and discharge_possible and trade_profitable:
        decision = "ontladen"
    elif (
        current_is_best_charge
        and free_capacity_kwh is not None
        and free_capacity_kwh > MIN_ENERGY_KWH
        and trade_profitable
        and not solar_charge_delay
    ):
        decision = "handelsladen"
    elif solar_charge_delay or trade_profitable:
        decision = "wachten"
    else:
        decision = "geen_actie"

    return {
        "planner_preview_status": "ready" if valid else "waiting_for_energy_balance",
        "planner_preview_decision": decision,
        "planner_preview_required_min_soc": round(required_min_soc, 1),
        "planner_preview_safety_charge_needed": safety_charge_needed,
        "planner_preview_safety_charge_kwh": (
            round(additional_kwh, 3) if additional_kwh is not None else None
        ),
        "planner_preview_safety_charge_slots": selected_slots,
        "planner_preview_safety_schedule_sufficient": (
            not safety_charge_needed or remaining <= MIN_ENERGY_KWH
        ),
        "planner_preview_discharge_possible": discharge_possible,
        "planner_preview_free_capacity_kwh": (
            round(free_capacity_kwh, 3) if free_capacity_kwh is not None else None
        ),
        "planner_preview_charge_efficiency_percent": round(charge_eff * 100.0, 1),
        "planner_preview_discharge_efficiency_percent": round(discharge_eff * 100.0, 1),
        "planner_preview_roundtrip_efficiency_percent": round(roundtrip_eff * 100.0, 1),
        "planner_preview_minimum_trade_margin": round(min_margin, 4),
        "planner_preview_trade_profitable": trade_profitable,
        "planner_preview_best_charge_time": (
            best_trade["charge_time"].isoformat() if best_trade else None
        ),
        "planner_preview_best_discharge_time": (
            best_trade["discharge_time"].isoformat() if best_trade else None
        ),
        "planner_preview_expected_trade_margin": (
            round(best_trade["net_margin"], 6) if best_trade else None
        ),
        "planner_preview_max_charge_power_w": settings.max_charge_power_w,
        "planner_preview_max_discharge_power_w": settings.max_discharge_power_w,
        "planner_preview_resolution_minutes": SLOT_MINUTES,
        "planner_preview_slot_count": len(rows),
        "planner_preview_observational_only": True,
        "planner_preview_execution_enabled": False,
    }


def build_72h_plan_preview(
    forecast: list[dict[str, Any]],
    soc: float | None,
    settings: EMSSettings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Sequential 288-slot plan preserving the frozen priority order."""
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = _normalize_slots(forecast, now_utc)
    if soc is None:
        return {
            "auto_plan_72h_status": "waiting_for_soc",
            "auto_plan_72h_valid": False,
            "auto_plan_72h_plan": [],
            "auto_plan_72h_count": 0,
            "auto_plan_72h_execution_enabled": False,
        }
    if not rows:
        return {
            "auto_plan_72h_status": "waiting_for_forecast",
            "auto_plan_72h_valid": False,
            "auto_plan_72h_plan": [],
            "auto_plan_72h_count": 0,
            "auto_plan_72h_execution_enabled": False,
        }

    energy_need = build_energy_need_analysis(forecast, soc, settings, now=now_utc)
    preview = build_planner_preview(forecast, energy_need, soc, settings, now=now_utc)

    capacity = settings.battery_capacity_kwh
    min_stored = capacity * settings.technical_min_soc_percent / 100.0
    max_stored = capacity * settings.max_soc_percent / 100.0
    charge_eff = settings.charge_efficiency_percent / 100.0
    discharge_eff = settings.discharge_efficiency_percent / 100.0
    execution_buffer_kwh = capacity * EXECUTION_BUFFER_PERCENT / 100.0
    reserve_kwh = capacity * settings.software_reserve_percent / 100.0

    start_soc = max(
        float(settings.technical_min_soc_percent),
        min(float(settings.max_soc_percent), float(soc)),
    )
    stored_kwh = capacity * start_soc / 100.0

    best_charge_time = _parse_time(preview.get("planner_preview_best_charge_time"))
    best_discharge_time = _parse_time(preview.get("planner_preview_best_discharge_time"))
    trade_profitable = bool(preview.get("planner_preview_trade_profitable"))
    best_discharge_price = None
    if best_discharge_time is not None:
        for row in rows:
            if row["time"] == best_discharge_time:
                best_discharge_price = row["export_price"]
                break

    plan: list[dict[str, Any]] = []
    trade_reserved = 0.0
    min_soc_seen = start_soc
    max_soc_seen = start_soc
    buffer_breaches = 0

    for index, row in enumerate(rows):
        fraction = _slot_fraction(row["time"], now_utc)
        home = max(0.0, row["home_kwh"] or 0.0) * fraction
        solar = max(0.0, row["solar_kwh"] or 0.0) * fraction
        charge_limit = settings.max_charge_power_w / 1000.0 * SLOT_HOURS * fraction
        discharge_limit = settings.max_discharge_power_w / 1000.0 * SLOT_HOURS * fraction

        next_usable = _next_usable_solar_index(rows, index + 1)
        need_until_solar = 0.0
        if next_usable is not None:
            for future in rows[index + 1 : next_usable]:
                future_home = max(0.0, future["home_kwh"] or 0.0)
                future_solar = max(0.0, future["solar_kwh"] or 0.0)
                need_until_solar += max(future_home - future_solar, 0.0) / discharge_eff
        reserve_floor = min(max_stored, min_stored + reserve_kwh + need_until_solar)
        execution_floor = min(max_stored, reserve_floor + execution_buffer_kwh)

        solar_to_home = min(solar, home)
        solar_surplus = max(0.0, solar - solar_to_home)
        home_deficit = max(0.0, home - solar_to_home)

        solar_charge_input = min(
            solar_surplus,
            charge_limit,
            max(0.0, (max_stored - stored_kwh) / charge_eff),
        )
        stored_kwh += solar_charge_input * charge_eff
        remaining_charge_limit = max(0.0, charge_limit - solar_charge_input)

        grid_safety_input = 0.0
        if stored_kwh < execution_floor - MIN_ENERGY_KWH:
            grid_safety_input = min(
                remaining_charge_limit,
                max(0.0, (execution_floor - stored_kwh) / charge_eff),
                max(0.0, (max_stored - stored_kwh) / charge_eff),
            )
            stored_kwh += grid_safety_input * charge_eff
            remaining_charge_limit -= grid_safety_input

        grid_trade_input = 0.0
        if (
            trade_profitable
            and best_charge_time is not None
            and row["time"] == best_charge_time
            and remaining_charge_limit > MIN_ENERGY_KWH
        ):
            free_input = max(0.0, (max_stored - stored_kwh) / charge_eff)
            effective_charge_cost = (
                row["import_price"] / (charge_eff * discharge_eff)
                if row["import_price"] is not None
                else None
            )
            margin = (
                best_discharge_price - effective_charge_cost
                if best_discharge_price is not None and effective_charge_cost is not None
                else None
            )
            if (
                margin is not None
                and margin >= settings.minimum_trade_margin_eur_per_kwh
            ):
                grid_trade_input = min(remaining_charge_limit, free_input)
                stored_added = grid_trade_input * charge_eff
                stored_kwh += stored_added
                trade_reserved += stored_added

        operational_floor = min(
            max_stored, max(execution_floor, execution_floor + trade_reserved)
        )
        max_output_from_storage = max(
            0.0, (stored_kwh - operational_floor) * discharge_eff
        )

        threshold = None
        if best_charge_time is not None:
            best_buy = next(
                (
                    item["import_price"]
                    for item in rows
                    if item["time"] == best_charge_time
                ),
                None,
            )
            if best_buy is not None:
                threshold = (
                    best_buy / (charge_eff * discharge_eff)
                    + settings.minimum_trade_margin_eur_per_kwh
                )

        allow_home_discharge = trade_reserved <= MIN_ENERGY_KWH
        if (
            row["import_price"] is not None
            and threshold is not None
            and row["import_price"] >= threshold
        ):
            allow_home_discharge = True

        discharge_to_home = 0.0
        if allow_home_discharge:
            discharge_to_home = min(
                home_deficit, discharge_limit, max_output_from_storage
            )
            if discharge_to_home > MIN_ENERGY_KWH:
                used = discharge_to_home / discharge_eff
                stored_kwh -= used
                home_deficit -= discharge_to_home
                trade_reserved = max(0.0, trade_reserved - used)

        discharge_to_grid = 0.0
        if (
            trade_profitable
            and best_discharge_time is not None
            and row["time"] == best_discharge_time
        ):
            remaining_output = max(0.0, discharge_limit - discharge_to_home)
            available = max(0.0, (stored_kwh - execution_floor) * discharge_eff)
            discharge_to_grid = min(remaining_output, available)
            if discharge_to_grid > MIN_ENERGY_KWH:
                used = discharge_to_grid / discharge_eff
                stored_kwh -= used
                trade_reserved = max(0.0, trade_reserved - used)

        stored_kwh = max(min_stored, min(max_stored, stored_kwh))
        soc_start = plan[-1]["soc_end"] if plan else start_soc
        soc_end = stored_kwh / capacity * 100.0
        min_soc_seen = min(min_soc_seen, soc_end)
        max_soc_seen = max(max_soc_seen, soc_end)
        execution_floor_soc = execution_floor / capacity * 100.0
        execution_headroom = soc_end - execution_floor_soc
        if execution_headroom < -0.05:
            buffer_breaches += 1

        action: list[str] = []
        if grid_safety_input > MIN_ENERGY_KWH:
            action.append("veiligheidsladen")
        if grid_trade_input > MIN_ENERGY_KWH:
            action.append("handelsladen")
        if solar_charge_input > MIN_ENERGY_KWH:
            action.append("zonneladen")
        if discharge_to_home > MIN_ENERGY_KWH:
            action.append("woning_ontladen")
        if discharge_to_grid > MIN_ENERGY_KWH:
            action.append("handel_ontladen")
        if not action:
            action.append("geen_actie")

        plan.append(
            {
                "time": row["time"].isoformat(),
                "import_price": row["import_price"],
                "export_price": row["export_price"],
                "solar_kwh": round(solar, 3),
                "home_consumption_kwh": round(home, 3),
                "charge_from_solar_kwh": round(solar_charge_input, 3),
                "charge_from_grid_safety_kwh": round(grid_safety_input, 3),
                "charge_from_grid_trade_kwh": round(grid_trade_input, 3),
                "discharge_to_home_kwh": round(discharge_to_home, 3),
                "discharge_to_grid_kwh": round(discharge_to_grid, 3),
                "grid_import_for_home_kwh": round(max(0.0, home_deficit), 3),
                "soc_start": round(float(soc_start), 1),
                "soc_end": round(soc_end, 1),
                "execution_reserve_floor_soc": round(execution_floor_soc, 1),
                "execution_buffer_percent": EXECUTION_BUFFER_PERCENT,
                "action": "+".join(action),
                "observational_only": True,
            }
        )

    return {
        "auto_plan_72h_status": "ready",
        "auto_plan_72h_valid": len(plan) == FORECAST_SLOTS,
        "auto_plan_72h_plan": plan,
        "auto_plan_72h_count": len(plan),
        "auto_plan_72h_resolution_minutes": SLOT_MINUTES,
        "auto_plan_72h_expected_slot_count": FORECAST_SLOTS,
        "auto_plan_72h_start_soc": round(start_soc, 1),
        "auto_plan_72h_end_soc": plan[-1]["soc_end"] if plan else round(start_soc, 1),
        "auto_plan_72h_min_soc": round(min_soc_seen, 1),
        "auto_plan_72h_max_soc": round(max_soc_seen, 1),
        "auto_plan_72h_execution_buffer_percent": EXECUTION_BUFFER_PERCENT,
        "auto_plan_72h_execution_buffer_breach_slots": buffer_breaches,
        "auto_plan_72h_execution_buffer_safe": buffer_breaches == 0,
        "auto_plan_72h_battery_capacity_kwh": settings.battery_capacity_kwh,
        "auto_plan_72h_technical_min_soc_percent": settings.technical_min_soc_percent,
        "auto_plan_72h_max_soc_percent": settings.max_soc_percent,
        "auto_plan_72h_max_charge_power_w": settings.max_charge_power_w,
        "auto_plan_72h_max_discharge_power_w": settings.max_discharge_power_w,
        "auto_plan_72h_charge_efficiency_percent": settings.charge_efficiency_percent,
        "auto_plan_72h_discharge_efficiency_percent": settings.discharge_efficiency_percent,
        "auto_plan_72h_minimum_trade_margin_eur_per_kwh": settings.minimum_trade_margin_eur_per_kwh,
        "auto_plan_72h_software_reserve_percent": settings.software_reserve_percent,
        "auto_plan_72h_startup_delay_seconds": settings.startup_delay_seconds,
        "auto_plan_72h_startup_gate_active": False,
        "auto_plan_72h_observational_only": True,
        "auto_plan_72h_execution_enabled": False,
        "physical_execution_authority": False,
    }
