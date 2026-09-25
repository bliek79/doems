"""DOEMS Alpha20 compact cheapest-energy safety policy.

This production-only policy keeps the frozen Alpha76/G5 reference untouched.
It reuses the existing public contracts and charge categories. No new public
sensor, charge stream or purpose is introduced.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .ems_alpha76.energy_need import build_energy_need_analysis as _frozen_energy_need
from .ems_alpha76.planner_preview import build_planner_preview as _frozen_preview
from .ems_alpha76.planner_72h import build_72h_plan_preview as _frozen_plan72
from .ems_alpha76_adapter import EXECUTION_BUFFER_PERCENT, forecast_from_input, planner_reference
from .ems_settings import EMSSettings

POLICY_VERSION = "alpha20_cheapest_energy_safety_v1"
_MIN_ENERGY_KWH = 0.01


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = dt_util.parse_datetime(str(value))
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return parsed.astimezone(dt_util.UTC)


def _hour_fraction(hour: datetime, now_utc: datetime) -> float:
    current_hour = now_utc.replace(minute=0, second=0, microsecond=0)
    if hour != current_hour:
        return 1.0
    elapsed = now_utc.minute / 60.0 + now_utc.second / 3600.0
    return max(0.0, min(1.0, 1.0 - elapsed))


def _rows(forecast: list[dict[str, Any]], now_utc: datetime) -> list[dict[str, Any]]:
    current_hour = now_utc.replace(minute=0, second=0, microsecond=0)
    rows: list[dict[str, Any]] = []
    for raw in forecast:
        hour = _parse_time(raw.get("time"))
        if hour is None or hour < current_hour:
            continue
        solar_raw = _as_float(raw.get("solar_kwh"))
        home_raw = _as_float(raw.get("home_consumption_kwh"))
        solar_valid = raw.get("solar_forecast_valid")
        if solar_valid is None:
            solar_valid = solar_raw is not None
        import_price = _as_float(raw.get("import_price"))
        if import_price is None:
            import_price = _as_float(raw.get("price"))
        export_price = _as_float(raw.get("export_price"))
        if export_price is None:
            export_price = import_price
        rows.append(
            {
                "time": hour,
                "import_price": import_price,
                "export_price": export_price,
                "price_source": raw.get("price_source"),
                "import_price_source": raw.get("import_price_source") or raw.get("price_source"),
                "export_price_source": raw.get("export_price_source") or raw.get("price_source"),
                "solar_forecast_valid": bool(solar_valid),
                "solar_kwh": max(0.0, solar_raw or 0.0),
                "home_kwh": max(0.0, home_raw or 0.0),
                "home_valid": home_raw is not None,
            }
        )
    rows.sort(key=lambda item: item["time"])
    return rows[:72]


def _next_usable_solar(rows: list[dict[str, Any]], start_index: int) -> tuple[int | None, datetime | None]:
    for index in range(start_index, len(rows) - 1):
        first = rows[index]
        second = rows[index + 1]
        if (
            first["solar_forecast_valid"]
            and second["solar_forecast_valid"]
            and first["solar_kwh"] > 0
            and second["solar_kwh"] > 0
            and first["solar_kwh"] >= first["home_kwh"]
            and second["solar_kwh"] >= second["home_kwh"]
        ):
            return index, first["time"]
    return None, None


def _simulate_house_route(
    rows: list[dict[str, Any]],
    *,
    start_stored_kwh: float,
    minimum_stored_kwh: float,
    max_stored_kwh: float,
    charge_eff: float,
    discharge_eff: float,
    max_charge_power_w: int,
    max_discharge_power_w: int,
    now_utc: datetime,
    safety_schedule_stored_kwh: dict[str, float],
) -> list[dict[str, Any]]:
    stored_kwh = start_stored_kwh
    trace: list[dict[str, Any]] = []
    for row in rows:
        fraction = _hour_fraction(row["time"], now_utc)
        solar = row["solar_kwh"] * fraction
        home = row["home_kwh"] * fraction
        solar_to_home = min(solar, home)
        solar_surplus = max(0.0, solar - solar_to_home)
        home_deficit = max(0.0, home - solar_to_home)

        charge_input_limit = max_charge_power_w / 1000.0 * fraction
        discharge_output_limit = max_discharge_power_w / 1000.0 * fraction

        solar_charge_input = min(
            solar_surplus,
            charge_input_limit,
            max(0.0, max_stored_kwh - stored_kwh) / charge_eff,
        )
        stored_kwh = min(max_stored_kwh, stored_kwh + solar_charge_input * charge_eff)
        available_charge_input = max(0.0, charge_input_limit - solar_charge_input)

        maximum_safety_stored = min(
            available_charge_input * charge_eff,
            max(0.0, max_stored_kwh - stored_kwh),
        )
        key = row["time"].isoformat()
        requested_stored = max(0.0, _as_float(safety_schedule_stored_kwh.get(key)) or 0.0)
        actual_safety_stored = min(requested_stored, maximum_safety_stored)
        stored_kwh += actual_safety_stored

        available_output = max(0.0, (stored_kwh - minimum_stored_kwh) * discharge_eff)
        battery_to_home = min(home_deficit, discharge_output_limit, available_output)
        if battery_to_home > _MIN_ENERGY_KWH:
            stored_kwh -= battery_to_home / discharge_eff
            home_deficit -= battery_to_home

        trace.append(
            {
                "time": row["time"],
                "import_price": row["import_price"],
                "export_price": row["export_price"],
                "price_source": row["price_source"],
                "stored_end_kwh": stored_kwh,
                "grid_home_kwh": max(0.0, home_deficit),
                "maximum_safety_stored_kwh": maximum_safety_stored,
                "actual_safety_stored_kwh": actual_safety_stored,
                "remaining_safety_stored_headroom_kwh": max(
                    0.0, maximum_safety_stored - actual_safety_stored
                ),
            }
        )
    return trace


def _cheapest_safety_schedule(
    rows: list[dict[str, Any]],
    *,
    start_stored_kwh: float,
    minimum_stored_kwh: float,
    reserve_target_stored_kwh: float,
    max_stored_kwh: float,
    charge_eff: float,
    discharge_eff: float,
    max_charge_power_w: int,
    max_discharge_power_w: int,
    now_utc: datetime,
) -> tuple[dict[str, float], list[dict[str, Any]], int, int]:
    schedule: dict[str, float] = {}

    def simulate(current: dict[str, float]) -> list[dict[str, Any]]:
        return _simulate_house_route(
            rows,
            start_stored_kwh=start_stored_kwh,
            minimum_stored_kwh=minimum_stored_kwh,
            max_stored_kwh=max_stored_kwh,
            charge_eff=charge_eff,
            discharge_eff=discharge_eff,
            max_charge_power_w=max_charge_power_w,
            max_discharge_power_w=max_discharge_power_w,
            now_utc=now_utc,
            safety_schedule_stored_kwh=current,
        )

    initial = simulate(schedule)
    initial_breaches = sum(
        1
        for item in initial
        if item["stored_end_kwh"] < reserve_target_stored_kwh - _MIN_ENERGY_KWH
    )

    for _ in range(max(1, len(rows) * 4)):
        trace = simulate(schedule)
        breach_index = next(
            (
                index
                for index, item in enumerate(trace)
                if item["stored_end_kwh"] < reserve_target_stored_kwh - _MIN_ENERGY_KWH
            ),
            None,
        )
        if breach_index is None:
            break

        breach_stored = trace[breach_index]["stored_end_kwh"]
        required_improvement = reserve_target_stored_kwh - breach_stored
        candidates = [
            index
            for index, item in enumerate(trace[: breach_index + 1])
            if item["import_price"] is not None
            and item["remaining_safety_stored_headroom_kwh"] > _MIN_ENERGY_KWH
        ]
        candidates.sort(
            key=lambda index: (
                trace[index]["import_price"],
                -trace[index]["time"].timestamp(),
            )
        )

        allocation_made = False
        for candidate_index in candidates:
            candidate = trace[candidate_index]
            maximum_add = candidate["remaining_safety_stored_headroom_kwh"]
            key = candidate["time"].isoformat()
            existing = schedule.get(key, 0.0)
            trial = dict(schedule)
            trial[key] = existing + maximum_add
            trial_trace = simulate(trial)
            maximum_improvement = trial_trace[breach_index]["stored_end_kwh"] - breach_stored
            if maximum_improvement <= _MIN_ENERGY_KWH:
                continue

            allocation = maximum_add
            if maximum_improvement > required_improvement + _MIN_ENERGY_KWH:
                low, high = 0.0, maximum_add
                for _binary in range(18):
                    mid = (low + high) / 2.0
                    probe = dict(schedule)
                    probe[key] = existing + mid
                    probe_trace = simulate(probe)
                    improvement = probe_trace[breach_index]["stored_end_kwh"] - breach_stored
                    if improvement >= required_improvement:
                        high = mid
                    else:
                        low = mid
                allocation = high

            if allocation <= _MIN_ENERGY_KWH:
                continue
            schedule[key] = existing + allocation
            allocation_made = True
            break

        if not allocation_made:
            break

    final = simulate(schedule)
    final_breaches = sum(
        1
        for item in final
        if item["stored_end_kwh"] < reserve_target_stored_kwh - _MIN_ENERGY_KWH
    )
    return schedule, final, initial_breaches, final_breaches


def _override_energy_need(
    frozen: dict[str, Any],
    rows: list[dict[str, Any]],
    soc_percent: float | None,
) -> dict[str, Any]:
    result = deepcopy(frozen)
    no_usable = result.get("energy_need_first_usable_solar") is None
    complete = bool(rows) and all(
        row["home_valid"] and row["solar_forecast_valid"] for row in rows
    )
    if no_usable and complete and soc_percent is not None:
        result["energy_need_status"] = "ready"
        result["energy_need_valid"] = True
        result["energy_need_reason"] = (
            "Geen twee opeenvolgende bruikbare zonne-uren binnen de horizon; "
            "de volledige 72-uurs forecast blijft planbaar"
        )
        result["energy_need_usable_solar_rule"] = (
            "eerste van twee opeenvolgende forecasturen waarin solar >= woningverbruik; "
            "bij ontbreken blijft de volledige horizon planbaar"
        )
    return result


def _build_preview(
    frozen: dict[str, Any],
    rows: list[dict[str, Any]],
    settings: EMSSettings,
    soc_percent: float,
    now_utc: datetime,
) -> tuple[dict[str, Any], dict[str, float]]:
    result = deepcopy(frozen)
    capacity = max(0.1, float(settings.battery_capacity_kwh))
    min_soc = max(0.0, min(100.0, float(settings.technical_min_soc_percent)))
    max_soc = max(min_soc, min(100.0, float(settings.max_soc_percent)))
    reserve_pct = max(0.0, min(30.0, float(settings.software_reserve_percent)))
    charge_eff = max(0.50, min(1.0, float(settings.charge_efficiency_percent) / 100.0))
    discharge_eff = max(0.50, min(1.0, float(settings.discharge_efficiency_percent) / 100.0))
    max_stored = capacity * max_soc / 100.0
    minimum_stored = capacity * min_soc / 100.0
    reserve_target_stored = min(max_stored, minimum_stored + capacity * reserve_pct / 100.0)
    start_stored = min(max_stored, max(minimum_stored, capacity * float(soc_percent) / 100.0))

    schedule, final_trace, initial_breaches, final_breaches = _cheapest_safety_schedule(
        rows,
        start_stored_kwh=start_stored,
        minimum_stored_kwh=minimum_stored,
        reserve_target_stored_kwh=reserve_target_stored,
        max_stored_kwh=max_stored,
        charge_eff=charge_eff,
        discharge_eff=discharge_eff,
        max_charge_power_w=settings.max_charge_power_w,
        max_discharge_power_w=settings.max_discharge_power_w,
        now_utc=now_utc,
    )

    selected_hours: list[dict[str, Any]] = []
    roundtrip_eff = charge_eff * discharge_eff
    by_time = {item["time"].isoformat(): item for item in final_trace}
    for key, stored_kwh in sorted(schedule.items()):
        trace = by_time.get(key)
        if trace is None or stored_kwh <= _MIN_ENERGY_KWH:
            continue
        selected_hours.append(
            {
                "time": key,
                "price": trace["import_price"],
                "import_price": trace["import_price"],
                "export_price": trace["export_price"],
                "price_source": trace["price_source"],
                "max_battery_energy_kwh": round(
                    trace["maximum_safety_stored_kwh"], 3
                ),
                "candidate_battery_energy_kwh": round(stored_kwh, 3),
            }
        )

    safety_needed = initial_breaches > 0
    current_hour = now_utc.replace(minute=0, second=0, microsecond=0)
    current_selected = any(_parse_time(item["time"]) == current_hour for item in selected_hours)

    result["planner_preview_required_min_soc"] = round(
        reserve_target_stored / capacity * 100.0, 1
    )
    result["planner_preview_energy_above_reserve_kwh"] = round(
        max(0.0, start_stored - reserve_target_stored), 3
    )
    result["planner_preview_safety_charge_needed"] = safety_needed
    result["planner_preview_safety_charge_kwh"] = round(sum(schedule.values()), 3)
    result["planner_preview_safety_charge_hours"] = selected_hours
    result["planner_preview_safety_charge_hour_count"] = len(selected_hours)
    result["planner_preview_safety_schedule_sufficient"] = final_breaches == 0
    # Household safety takes priority over optional trading.
    result["planner_preview_trade_profitable"] = bool(
        result.get("planner_preview_trade_profitable") and not safety_needed
    )
    result["planner_preview_trade_charge_candidate"] = bool(
        result.get("planner_preview_trade_charge_candidate") and not safety_needed
    )

    if safety_needed:
        if current_selected:
            result["planner_preview_decision"] = "veiligheidsladen"
            result["planner_preview_reason"] = (
                "De 72-uurs SOC-route dreigt onder de 5%+7% planningsmarge te "
                "komen; het huidige uur is een geselecteerd goedkoop veiligheidslaadvenster"
            )
        elif selected_hours:
            result["planner_preview_decision"] = "wachten"
            result["planner_preview_reason"] = (
                "De 72-uurs SOC-route vraagt veiligheidslading; een goedkoper "
                "technisch haalbaar laadvenster ligt later"
            )
        else:
            result["planner_preview_decision"] = "wachten"
            result["planner_preview_reason"] = (
                "De 72-uurs SOC-route dreigt onder de planningsmarge te komen, "
                "maar de beschikbare laadvensters zijn technisch onvoldoende"
            )
    result["planner_preview_note"] = (
        "Alpha20 gebruikt uitsluitend bestaand veiligheidsladen voor de "
        "goedkoopste technisch haalbare energie om de rollende 72-uurs route "
        "rond de 5%+7% planningsmarge te houden; er komt geen extra laadtype."
    )
    return result, schedule


def _physical_plan(
    frozen: dict[str, Any],
    rows: list[dict[str, Any]],
    settings: EMSSettings,
    soc_percent: float,
    planner_preview: dict[str, Any],
    schedule_stored: dict[str, float],
    now_utc: datetime,
) -> dict[str, Any]:
    result = deepcopy(frozen)
    capacity = max(0.1, float(settings.battery_capacity_kwh))
    min_soc = max(0.0, min(100.0, float(settings.technical_min_soc_percent)))
    max_soc = max(min_soc, min(100.0, float(settings.max_soc_percent)))
    reserve_pct = max(0.0, min(30.0, float(settings.software_reserve_percent)))
    charge_eff = max(0.50, min(1.0, float(settings.charge_efficiency_percent) / 100.0))
    discharge_eff = max(0.50, min(1.0, float(settings.discharge_efficiency_percent) / 100.0))
    max_stored = capacity * max_soc / 100.0
    minimum_stored = capacity * min_soc / 100.0
    reserve_floor = min(max_stored, minimum_stored + capacity * reserve_pct / 100.0)
    execution_floor = min(
        max_stored,
        reserve_floor + capacity * EXECUTION_BUFFER_PERCENT / 100.0,
    )
    stored = min(max_stored, max(minimum_stored, capacity * float(soc_percent) / 100.0))
    start_soc = stored / capacity * 100.0
    safety_needed = bool(planner_preview.get("planner_preview_safety_charge_needed"))

    frozen_rows = {
        str(item.get("time")): item
        for item in (frozen.get("auto_plan_72h_plan") or [])
        if isinstance(item, dict)
    }

    plan: list[dict[str, Any]] = []
    totals = {
        "solar": 0.0,
        "safety": 0.0,
        "trade_charge": 0.0,
        "home": 0.0,
        "trade_discharge": 0.0,
        "grid_home": 0.0,
        "solar_export": 0.0,
    }
    min_soc_seen = start_soc
    max_soc_seen = start_soc
    minimum_execution_headroom = start_soc - execution_floor / capacity * 100.0
    execution_buffer_breaches = 0

    for index, row in enumerate(rows):
        hour = row["time"]
        fraction = _hour_fraction(hour, now_utc)
        charge_limit = settings.max_charge_power_w / 1000.0 * fraction
        discharge_limit = settings.max_discharge_power_w / 1000.0 * fraction
        solar = row["solar_kwh"] * fraction
        home = row["home_kwh"] * fraction
        solar_to_home = min(solar, home)
        solar_surplus = max(0.0, solar - solar_to_home)
        home_deficit = max(0.0, home - solar_to_home)

        soc_start = plan[-1]["soc_end"] if plan else start_soc
        available_charge_input = charge_limit

        solar_charge_input = min(
            solar_surplus,
            available_charge_input,
            max(0.0, max_stored - stored) / charge_eff,
        )
        stored += solar_charge_input * charge_eff
        available_charge_input -= solar_charge_input
        solar_surplus -= solar_charge_input

        requested_safety_stored = max(
            0.0, _as_float(schedule_stored.get(hour.isoformat())) or 0.0
        )
        grid_safety_input = min(
            requested_safety_stored / charge_eff,
            available_charge_input,
            max(0.0, max_stored - stored) / charge_eff,
        )
        stored += grid_safety_input * charge_eff
        available_charge_input -= grid_safety_input

        frozen_row = frozen_rows.get(hour.isoformat(), {})
        grid_trade_input = 0.0
        if not safety_needed:
            requested_trade = max(
                0.0, _as_float(frozen_row.get("charge_from_grid_trade_kwh")) or 0.0
            )
            grid_trade_input = min(
                requested_trade,
                available_charge_input,
                max(0.0, max_stored - stored) / charge_eff,
            )
            stored += grid_trade_input * charge_eff

        # Physical self_consumption: household demand can use the battery down
        # to the technical device minimum. A 12% planning target is maintained
        # by scheduling safety energy, not by pretending the battery stops here.
        available_output = max(0.0, (stored - minimum_stored) * discharge_eff)
        discharge_to_home = min(home_deficit, discharge_limit, available_output)
        if discharge_to_home > _MIN_ENERGY_KWH:
            stored -= discharge_to_home / discharge_eff
            home_deficit -= discharge_to_home

        grid_home = max(0.0, home_deficit)
        discharge_to_grid = 0.0
        if not safety_needed:
            requested_grid_discharge = max(
                0.0, _as_float(frozen_row.get("discharge_to_grid_kwh")) or 0.0
            )
            remaining_output = max(0.0, discharge_limit - discharge_to_home)
            available_trade_output = max(0.0, (stored - execution_floor) * discharge_eff)
            discharge_to_grid = min(
                requested_grid_discharge, remaining_output, available_trade_output
            )
            if discharge_to_grid > _MIN_ENERGY_KWH:
                stored -= discharge_to_grid / discharge_eff

        stored = max(minimum_stored, min(max_stored, stored))
        soc_end = stored / capacity * 100.0
        min_soc_seen = min(min_soc_seen, soc_end)
        max_soc_seen = max(max_soc_seen, soc_end)
        execution_headroom = soc_end - execution_floor / capacity * 100.0
        minimum_execution_headroom = min(
            minimum_execution_headroom, execution_headroom
        )
        if discharge_to_grid > _MIN_ENERGY_KWH and execution_headroom < -0.05:
            execution_buffer_breaches += 1

        usable_index, next_usable = _next_usable_solar(rows, index)
        stop = usable_index if usable_index is not None else len(rows)
        dynamic_need = 0.0
        for need_index in range(index, stop):
            need_row = rows[need_index]
            need_fraction = _hour_fraction(need_row["time"], now_utc)
            dynamic_need += max(
                0.0, need_row["home_kwh"] - need_row["solar_kwh"]
            ) * need_fraction
        if index + 1 < len(rows):
            usable_after_index, _ = _next_usable_solar(rows, index + 1)
            stop_after = usable_after_index if usable_after_index is not None else len(rows)
            dynamic_after = 0.0
            for need_index in range(index + 1, stop_after):
                need_row = rows[need_index]
                dynamic_after += max(
                    0.0, need_row["home_kwh"] - need_row["solar_kwh"]
                )
        else:
            dynamic_after = 0.0

        actions: list[str] = []
        if grid_safety_input > _MIN_ENERGY_KWH:
            actions.append("veiligheidsladen")
        if grid_trade_input > _MIN_ENERGY_KWH:
            actions.append("handelsladen")
        if solar_charge_input > _MIN_ENERGY_KWH:
            actions.append("zonneladen")
        if discharge_to_home > _MIN_ENERGY_KWH:
            actions.append("woning_ontladen")
        if discharge_to_grid > _MIN_ENERGY_KWH:
            actions.append("handel_ontladen")
        if not actions:
            actions.append("geen_actie")

        totals["solar"] += solar_charge_input
        totals["safety"] += grid_safety_input
        totals["trade_charge"] += grid_trade_input
        totals["home"] += discharge_to_home
        totals["trade_discharge"] += discharge_to_grid
        totals["grid_home"] += grid_home
        totals["solar_export"] += max(0.0, solar_surplus)

        plan.append(
            {
                "time": hour.isoformat(),
                "price": row["import_price"],
                "import_price": row["import_price"],
                "export_price": row["export_price"],
                "price_source": row["price_source"],
                "import_price_source": row["import_price_source"],
                "export_price_source": row["export_price_source"],
                "solar_kwh": round(solar, 3),
                "home_consumption_kwh": round(home, 3),
                "solar_to_home_kwh": round(solar_to_home, 3),
                "charge_from_solar_kwh": round(solar_charge_input, 3),
                "charge_from_grid_safety_kwh": round(grid_safety_input, 3),
                "charge_from_grid_trade_kwh": round(grid_trade_input, 3),
                "charge_from_grid_kwh": round(grid_safety_input + grid_trade_input, 3),
                "discharge_to_home_kwh": round(discharge_to_home, 3),
                "discharge_to_grid_kwh": round(discharge_to_grid, 3),
                "grid_import_for_home_kwh": round(grid_home, 3),
                "solar_export_kwh": round(max(0.0, solar_surplus), 3),
                "soc_start": round(float(soc_start), 1),
                "soc_end": round(soc_end, 1),
                "reserve_floor_soc": round(reserve_floor / capacity * 100.0, 1),
                "reserve_floor_start_soc": round(reserve_floor / capacity * 100.0, 1),
                "execution_reserve_floor_soc": round(
                    execution_floor / capacity * 100.0, 1
                ),
                "execution_reserve_floor_start_soc": round(
                    execution_floor / capacity * 100.0, 1
                ),
                "execution_buffer_percent": round(EXECUTION_BUFFER_PERCENT, 1),
                "execution_headroom_soc": round(execution_headroom, 1),
                "dynamic_need_until_solar_kwh": round(dynamic_need, 3),
                "dynamic_need_after_hour_kwh": round(dynamic_after, 3),
                "next_usable_solar": next_usable.isoformat() if next_usable else None,
                "solar_horizon_complete": next_usable is not None,
                "trade_reserved_kwh": 0.0,
                "action": "+".join(actions),
                "observational_only": True,
            }
        )

    result["auto_plan_72h_status"] = "ready"
    result["auto_plan_72h_valid"] = True
    result["auto_plan_72h_reason"] = (
        "72-uursplan: solar eerst; bestaand veiligheidsladen koopt vóór een "
        "verwachte 5%+7%-margebreuk de goedkoopste technisch haalbare netenergie"
    )
    result["auto_plan_72h_plan"] = plan
    result["auto_plan_72h_count"] = len(plan)
    result["auto_plan_72h_start"] = plan[0]["time"] if plan else None
    result["auto_plan_72h_end"] = plan[-1]["time"] if plan else None
    result["auto_plan_72h_start_soc"] = round(start_soc, 1)
    result["auto_plan_72h_end_soc"] = round(plan[-1]["soc_end"] if plan else start_soc, 1)
    result["auto_plan_72h_min_soc"] = round(min_soc_seen, 1)
    result["auto_plan_72h_max_soc"] = round(max_soc_seen, 1)
    result["auto_plan_72h_reserve_floor_soc"] = round(
        reserve_floor / capacity * 100.0, 1
    )
    result["auto_plan_72h_dynamic_reserve_min_soc"] = round(
        reserve_floor / capacity * 100.0, 1
    )
    result["auto_plan_72h_dynamic_reserve_max_soc"] = round(
        reserve_floor / capacity * 100.0, 1
    )
    result["auto_plan_72h_execution_buffer_percent"] = round(
        EXECUTION_BUFFER_PERCENT, 1
    )
    result["auto_plan_72h_execution_reserve_floor_soc"] = round(
        execution_floor / capacity * 100.0, 1
    )
    result["auto_plan_72h_execution_reserve_min_soc"] = round(
        execution_floor / capacity * 100.0, 1
    )
    result["auto_plan_72h_execution_reserve_max_soc"] = round(
        execution_floor / capacity * 100.0, 1
    )
    result["auto_plan_72h_min_execution_headroom_soc"] = round(
        minimum_execution_headroom, 1
    )
    result["auto_plan_72h_execution_buffer_breach_hours"] = execution_buffer_breaches
    result["auto_plan_72h_execution_buffer_safe"] = execution_buffer_breaches == 0
    result["auto_plan_72h_solar_charge_kwh"] = round(totals["solar"], 3)
    result["auto_plan_72h_grid_safety_charge_kwh"] = round(totals["safety"], 3)
    result["auto_plan_72h_grid_trade_charge_kwh"] = round(totals["trade_charge"], 3)
    result["auto_plan_72h_home_discharge_kwh"] = round(totals["home"], 3)
    result["auto_plan_72h_grid_trade_discharge_kwh"] = round(
        totals["trade_discharge"], 3
    )
    result["auto_plan_72h_grid_import_for_home_kwh"] = round(totals["grid_home"], 3)
    result["auto_plan_72h_solar_export_kwh"] = round(totals["solar_export"], 3)
    result["auto_plan_72h_trade_charge_stored_kwh"] = round(
        totals["trade_charge"] * charge_eff, 3
    )
    result["auto_plan_72h_note"] = (
        "Alpha20 houdt de publieke planner compact: alleen veiligheidsladen, "
        "handelsladen, zonneladen en woningontlading; geen support-laadtype."
    )
    return result


def build_policy_bundle(
    forecast: list[dict[str, Any]],
    *,
    settings: EMSSettings,
    soc_percent: float | None,
    now: datetime,
) -> dict[str, Any]:
    now_utc = now.astimezone(dt_util.UTC)
    rows = _rows(forecast, now_utc)
    need_frozen = _frozen_energy_need(
        forecast,
        soc_percent,
        settings.software_reserve_percent,
        battery_capacity_kwh=settings.battery_capacity_kwh,
        technical_min_soc_percent=settings.technical_min_soc_percent,
        max_soc_percent=settings.max_soc_percent,
        now=now_utc,
    )
    need = _override_energy_need(need_frozen, rows, soc_percent)
    preview_frozen = _frozen_preview(
        forecast,
        need,
        soc_percent,
        settings.charge_efficiency_percent,
        settings.discharge_efficiency_percent,
        settings.minimum_trade_margin_eur_per_kwh,
        max_charge_power_w=settings.max_charge_power_w,
        battery_capacity_kwh=settings.battery_capacity_kwh,
        technical_min_soc_percent=settings.technical_min_soc_percent,
        max_soc_percent=settings.max_soc_percent,
        now=now_utc,
    )
    if soc_percent is None:
        preview = preview_frozen
        schedule: dict[str, float] = {}
    else:
        preview, schedule = _build_preview(
            preview_frozen, rows, settings, soc_percent, now_utc
        )

    frozen_plan = _frozen_plan72(
        forecast,
        need,
        preview,
        soc_percent,
        settings.charge_efficiency_percent,
        settings.discharge_efficiency_percent,
        execution_buffer_percent=EXECUTION_BUFFER_PERCENT,
        max_charge_power_w=settings.max_charge_power_w,
        max_discharge_power_w=settings.max_discharge_power_w,
        battery_capacity_kwh=settings.battery_capacity_kwh,
        technical_min_soc_percent=settings.technical_min_soc_percent,
        max_soc_percent=settings.max_soc_percent,
        now=now_utc,
    )
    plan72 = (
        _physical_plan(
            frozen_plan,
            rows,
            settings,
            soc_percent,
            preview,
            schedule,
            now_utc,
        )
        if soc_percent is not None and rows
        else frozen_plan
    )
    return {
        "energy_need": deepcopy(need),
        "planner_preview": deepcopy(preview),
        "plan72": deepcopy(plan72),
        "ems_policy_source": POLICY_VERSION,
        "adapter_contract": "alpha41_288_to_72",
        "startup_delay_runtime_gate_active": False,
        "planner_runtime_active": True,
        "plan_store_write": True,
        "scheduler_invoked": True,
        "service_calls_performed": False,
        "physical_execution_authority": False,
    }


def run_ems_chain(
    *,
    input_result: dict[str, Any],
    settings: EMSSettings,
    soc_percent: float | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    reference = planner_reference(input_result, now)
    return build_policy_bundle(
        forecast_from_input(input_result),
        settings=settings,
        soc_percent=soc_percent,
        now=reference,
    )
