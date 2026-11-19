"""Alpha84 energy strategy: frozen hourly oracle and quarter-price adapter.

Original: dummy-os-anker-ems 0.0.1-alpha.84, commit
6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d (see ALPHA84_LICENSE).
The original 60-minute decision route remains unchanged. In native 15-minute
mode the same cheapest-feasible safety-window rule evaluates contiguous
physical windows using every distinct quarter import price and the existing
2-minute command preparation. This prevents treating each cheap price tick
as a new battery start. The 72-hour SOC authority remains native Plan72;
this module does not write to the Store or control the battery.
"""
from __future__ import annotations
from math import ceil
from datetime import datetime, timedelta, timezone
from typing import Any

_MIN_ENERGY_KWH = 0.01


class _Time:
    UTC = timezone.utc
    DEFAULT_TIME_ZONE = timezone.utc

    @staticmethod
    def utcnow():
        return datetime.now(timezone.utc)

    @staticmethod
    def parse_datetime(value):
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None


dt_util = _Time()


def _slot_start(now: datetime, interval_minutes: int) -> datetime:
    if isinstance(interval_minutes, bool) or interval_minutes not in (15, 60):
        raise ValueError("unsupported_planning_interval")
    return now.replace(minute=(now.minute // interval_minutes) * interval_minutes,
                       second=0, microsecond=0)

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



def build_energy_need_analysis(
    forecast: list[dict[str, Any]],
    soc: float | None,
    safety_reserve_percent: float,
    now: datetime | None = None,
    *, capacity_kwh: float = 7.2, min_soc_percent: float = 5.0,
    interval_minutes: int = 60,
) -> dict[str, Any]:
    """Build an observational energy balance until usable solar returns.

    Usable solar is deliberately conservative in this first observational
    version: the first hour of two consecutive forecast hours where solar
    production is at least equal to the forecast home consumption.
    """
    now_utc = (now or dt_util.utcnow()).astimezone(dt_util.UTC)
    _slot_start(now_utc, interval_minutes)
    reserve_percent = max(0.0, min(30.0, float(safety_reserve_percent)))
    reserve_kwh = capacity_kwh * reserve_percent / 100.0

    rows: list[dict[str, Any]] = []
    for raw in forecast:
        hour = _parse_time(raw.get("time"))
        home = _as_float(raw.get("home_consumption_kwh"))
        solar = _as_float(raw.get("solar_kwh"))
        if hour is None:
            continue
        rows.append({"time": hour, "home": home, "solar": solar})
    rows.sort(key=lambda item: item["time"])

    usable_index: int | None = None
    solar_span = 120 // interval_minutes
    for index in range(len(rows) - solar_span + 1):
        block = rows[index:index + solar_span]
        if block[0]["time"] < _slot_start(now_utc, interval_minutes):
            continue
        if all(row["home"] is not None and row["solar"] is not None
               and row["solar"] > 0 and row["solar"] >= row["home"]
               and row["time"] == block[0]["time"] + timedelta(minutes=offset * interval_minutes)
               for offset, row in enumerate(block)):
            usable_index = index
            break

    missing_home = False
    missing_solar = False
    net_need_kwh = 0.0
    contributing_hours = 0.0
    first_usable = rows[usable_index]["time"] if usable_index is not None else None

    for index, row in enumerate(rows):
        if row["time"] < _slot_start(now_utc, interval_minutes):
            continue
        if usable_index is not None and index >= usable_index:
            break

        home = row["home"]
        solar = row["solar"]
        if home is None:
            missing_home = True
            continue
        if solar is None:
            missing_solar = True
            solar = 0.0

        fraction = 1.0
        if row["time"] == _slot_start(now_utc, interval_minutes):
            elapsed = ((now_utc.minute % interval_minutes) + now_utc.second / 60.0) / interval_minutes
            fraction = max(0.0, min(1.0, 1.0 - elapsed))

        net_need_kwh += max(home - solar, 0.0) * fraction
        contributing_hours += fraction * interval_minutes / 60

    available_battery_kwh: float | None = None
    if soc is not None:
        usable_soc = max(0.0, min(100.0, float(soc)) - min_soc_percent)
        available_battery_kwh = capacity_kwh * usable_soc / 100.0

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

    # A missing usable-solar block is no longer a reason to stop planning.
    # In a low-solar period the complete available horizon is exactly the period
    # for which cheapest-energy safety planning is needed.
    valid = (
        not missing_home
        and not missing_solar
        and available_battery_kwh is not None
        and bool(rows)
    )

    if available_battery_kwh is None:
        reason = "SOC niet beschikbaar; batterij-energiebalans kan niet worden bepaald"
    elif missing_home or missing_solar:
        reason = "Forecast bevat ontbrekende woning- of solarwaarden voor de benodigde periode"
    elif first_usable is None:
        reason = (
            "Geen twee opeenvolgende bruikbare zonne-uren binnen de horizon; "
            "Energy Need gebruikt daarom de volledige beschikbare forecast"
        )
    elif additional_grid_charge_kwh is not None and additional_grid_charge_kwh > 0.01:
        reason = "Aanvullende energie nodig om behoefte plus veiligheidsreserve te dekken"
    else:
        reason = "Beschikbare batterij-energie dekt behoefte plus veiligheidsreserve"

    return {
        "energy_need_status": "ready" if valid else "waiting_for_complete_forecast",
        "energy_need_valid": valid,
        "energy_need_reason": reason,
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
        "energy_need_battery_capacity_kwh": capacity_kwh,
        "energy_need_min_soc_percent": min_soc_percent,
        "energy_need_usable_solar_rule": (
            "eerste van twee opeenvolgende forecasturen waarin solar >= woningverbruik; "
            "bij ontbreken blijft de volledige horizon planbaar"
        ),
        "energy_need_observational_only": True,
    }



def build_planner_preview(
    forecast: list[dict[str, Any]],
    energy_need: dict[str, Any],
    soc: float | None,
    charge_efficiency_percent: float,
    discharge_efficiency_percent: float,
    minimum_trade_margin: float,
    max_charge_power_w: int = 3500,
    max_discharge_power_w: int = 3500,
    now: datetime | None = None,
    *, capacity_kwh: float = 7.2, min_soc_percent: float = 5.0,
    interval_minutes: int = 60,
    protected_intervals: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Build an observational planner and financial trade preview.

    Alpha23 still creates no plans and performs no physical trading action.
    """
    now_utc = (now or dt_util.utcnow()).astimezone(dt_util.UTC)
    _slot_start(now_utc, interval_minutes)
    current_hour = _slot_start(now_utc, interval_minutes)

    charge_eff = max(0.50, min(1.00, float(charge_efficiency_percent) / 100.0))
    discharge_eff = max(0.50, min(1.00, float(discharge_efficiency_percent) / 100.0))
    roundtrip_eff = charge_eff * discharge_eff
    interval_epsilon = _MIN_ENERGY_KWH * interval_minutes / 60.0
    min_margin = max(0.0, float(minimum_trade_margin))

    valid = bool(energy_need.get("energy_need_valid"))
    need_kwh = _as_float(energy_need.get("energy_need_until_solar_kwh")) or 0.0
    reserve_kwh = _as_float(energy_need.get("energy_need_safety_reserve_kwh")) or 0.0
    additional_kwh = _as_float(energy_need.get("energy_need_additional_grid_charge_kwh"))
    tradable_kwh = _as_float(energy_need.get("energy_need_tradable_battery_kwh"))
    first_usable = _parse_time(energy_need.get("energy_need_first_usable_solar"))

    # The compact safety contract is the existing technical minimum plus the
    # configured software reserve. Forecast demand remains planning context and
    # must not become a fictitious self_consumption hold floor.
    required_min_soc = min_soc_percent + (
        reserve_kwh / capacity_kwh * 100.0
    )
    required_min_soc = max(float(min_soc_percent), min(100.0, required_min_soc))
    if soc is not None:
        tradable_kwh = max(
            0.0,
            capacity_kwh
            * (min(100.0, float(soc)) - required_min_soc)
            / 100.0,
        )

    price_rows: list[dict[str, Any]] = []
    for raw in forecast:
        hour = _parse_time(raw.get("time"))
        import_price = _as_float(raw.get("import_price"))
        if import_price is None:
            import_price = _as_float(raw.get("price"))
        export_price = _as_float(raw.get("export_price"))
        if export_price is None:
            export_price = import_price
        if hour is None or import_price is None or export_price is None or hour < current_hour:
            continue
        price_rows.append(
            {
                "time": hour,
                "price": import_price,
                "import_price": import_price,
                "export_price": export_price,
                "price_source": raw.get("price_source"),
                "import_price_source": raw.get("import_price_source") or raw.get("price_source"),
                "export_price_source": raw.get("export_price_source") or raw.get("price_source"),
                "solar_kwh": _as_float(raw.get("solar_kwh")),
                "home_consumption_kwh": _as_float(raw.get("home_consumption_kwh")),
            }
        )
    price_rows.sort(key=lambda item: item["time"])

    # When the four 15-minute import prices within every hour are identical,
    # preserve Alpha84's exact hourly safety-energy allocation and its frozen
    # numeric oracle. Only a genuinely quarter-varying price series needs the
    # contiguous physical-window ranking rather than four independently
    # cheapest quarter picks. This is an equality check, NOT hourly averaging.
    quarter_price_variation_prefix: list[bool] = []
    for j, row in enumerate(price_rows):
        changes_inside_hour = (j > 0 and interval_minutes == 15
            and row["time"].replace(minute=0, second=0, microsecond=0)
                == price_rows[j-1]["time"].replace(minute=0, second=0, microsecond=0)
            and row["import_price"] != price_rows[j-1]["import_price"])
        quarter_price_variation_prefix.append(changes_inside_hour or
            (quarter_price_variation_prefix[-1] if quarter_price_variation_prefix else False))

    prices = [row["import_price"] for row in price_rows]
    price_min = min(prices) if prices else None
    price_max = max(prices) if prices else None
    price_spread = (
        price_max - price_min if price_min is not None and price_max is not None else None
    )

    # Alpha80 cheapest-energy safety planner.
    #
    # Solar remains first priority. Normal self_consumption is projected down to
    # the technical device minimum. Whenever that rolling projection would end
    # an hour below technical minimum + software reserve, the planner looks back
    # over all technically feasible charge windows up to that deadline and buys
    # the required stored energy in the cheapest window. The complete 72-hour
    # route is then recalculated and the process repeats. This allows a later,
    # cheaper window to beat an earlier cheap window when the battery can safely
    # reach it, and allows a cheap window to fill to 100% when that is required
    # to bridge a later expensive period.
    minimum_stored_kwh = (
        capacity_kwh * float(min_soc_percent) / 100.0
    )
    reserve_target_stored_kwh = min(
        capacity_kwh,
        minimum_stored_kwh + reserve_kwh,
    )
    start_soc = (
        max(float(min_soc_percent), min(100.0, float(soc)))
        if soc is not None
        else float(min_soc_percent)
    )
    start_stored_kwh = capacity_kwh * start_soc / 100.0

    def _fraction(hour: datetime) -> float:
        if hour != current_hour:
            return 1.0
        elapsed = ((now_utc.minute % interval_minutes) + now_utc.second / 60.0) / interval_minutes
        return max(0.0, min(1.0, 1.0 - elapsed))

    def _simulate_safety(
        schedule_stored_kwh: dict[str, float],
    ) -> list[dict[str, Any]]:
        stored_kwh = start_stored_kwh
        trace: list[dict[str, Any]] = []
        for row in price_rows:
            protection = (protected_intervals or {}).get(row["time"].isoformat())
            if protection is not None:
                # Plan72 has already projected these immutable commitments.
                # They affect SOC before pricing decisions; this quarter has
                # zero room for an independently controlled automatic action.
                stored_kwh = max(minimum_stored_kwh,
                    min(capacity_kwh, stored_kwh + protection['stored_delta_kwh']))
                trace.append({"time": row["time"],
                    "import_price": row["import_price"],
                    "export_price": row["export_price"],
                    "price_source": row["price_source"],
                    "stored_end_kwh": stored_kwh,
                    "soc_end": stored_kwh / capacity_kwh * 100,
                    "grid_home_kwh": protection.get('grid_import_for_home_kwh', 0.0),
                    "solar_charge_input_kwh": protection.get('charge_from_solar_kwh', 0.0),
                    "maximum_safety_stored_kwh": 0.0,
                    "actual_safety_stored_kwh": 0.0,
                    "remaining_safety_stored_headroom_kwh": 0.0})
                continue
            fraction = _fraction(row["time"])
            solar = max(0.0, _as_float(row.get("solar_kwh")) or 0.0) * fraction
            home = max(0.0, _as_float(row.get("home_consumption_kwh")) or 0.0) * fraction
            solar_to_home = min(solar, home)
            solar_surplus = max(0.0, solar - solar_to_home)
            home_deficit = max(0.0, home - solar_to_home)

            charge_input_limit = max_charge_power_w / 1000.0 * fraction * interval_minutes / 60
            discharge_output_limit = max_discharge_power_w / 1000.0 * fraction * interval_minutes / 60

            solar_charge_input = min(
                solar_surplus,
                charge_input_limit,
                max(0.0, capacity_kwh - stored_kwh) / charge_eff,
            )
            stored_kwh = min(
                capacity_kwh,
                stored_kwh + solar_charge_input * charge_eff,
            )
            available_charge_input = max(0.0, charge_input_limit - solar_charge_input)

            maximum_safety_stored = min(
                available_charge_input * charge_eff,
                max(0.0, capacity_kwh - stored_kwh),
            )
            key = row["time"].isoformat()
            requested_safety_stored = max(
                0.0,
                _as_float(schedule_stored_kwh.get(key)) or 0.0,
            )
            actual_safety_stored = min(
                requested_safety_stored,
                maximum_safety_stored,
            )
            stored_kwh += actual_safety_stored

            available_output = max(
                0.0,
                (stored_kwh - minimum_stored_kwh) * discharge_eff,
            )
            battery_to_home = min(
                home_deficit,
                discharge_output_limit,
                available_output,
            )
            if battery_to_home > interval_epsilon:
                stored_kwh -= battery_to_home / discharge_eff
                home_deficit -= battery_to_home

            grid_home = max(0.0, home_deficit)
            trace.append(
                {
                    "time": row["time"],
                    "import_price": row["import_price"],
                    "export_price": row["export_price"],
                    "price_source": row["price_source"],
                    "stored_end_kwh": stored_kwh,
                    "soc_end": stored_kwh / capacity_kwh * 100.0,
                    "grid_home_kwh": grid_home,
                    "solar_charge_input_kwh": solar_charge_input,
                    "maximum_safety_stored_kwh": maximum_safety_stored,
                    "actual_safety_stored_kwh": actual_safety_stored,
                    "remaining_safety_stored_headroom_kwh": max(
                        0.0,
                        maximum_safety_stored - actual_safety_stored,
                    ),
                }
            )
        return trace

    safety_schedule: dict[str, float] = {}
    initial_trace = _simulate_safety(safety_schedule)
    initial_breach_count = sum(
        1
        for item in initial_trace
        if item["stored_end_kwh"] < reserve_target_stored_kwh - interval_epsilon
    )

    max_iterations = max(1, len(price_rows) * 4)
    for _ in range(max_iterations):
        trace = _simulate_safety(safety_schedule)
        breach_index = next(
            (
                index
                for index, item in enumerate(trace)
                if item["stored_end_kwh"]
                < reserve_target_stored_kwh - interval_epsilon
            ),
            None,
        )
        if breach_index is None:
            break

        breach_stored = trace[breach_index]["stored_end_kwh"]
        required_improvement = reserve_target_stored_kwh - breach_stored
        if (quarter_price_variation_prefix[breach_index]
                and required_improvement > interval_epsilon):
            # Alpha84 chooses the cheapest *feasible charging hour*, not a
            # different start/stop command at every price tick. At 15-minute
            # resolution evaluate complete contiguous physical charge windows
            # BEFORE action/three-slot construction. Each of the 288 distinct
            # prices is applied to its own expected AC energy; no hourly price
            # averaging, minimum-duration heuristic or new trade rule is used.
            # A new physical start loses exactly the already-approved 2 minutes.
            prices_now = [item["import_price"] for item in trace]
            headroom_now = [item["remaining_safety_stored_headroom_kwh"]
                            for item in trace]
            cost_prefix = [0.0]
            headroom_prefix = [0.0]
            blocked_prefix = [0]
            for j in range(breach_index + 1):
                cost_prefix.append(cost_prefix[-1] + prices_now[j] * .25)
                headroom_prefix.append(headroom_prefix[-1] + headroom_now[j])
                stamp = trace[j]["time"].isoformat()
                blocked_prefix.append(blocked_prefix[-1] + int(stamp in (protected_intervals or {})))
            trace_schedule_before = dict(safety_schedule)
            viable_windows = []
            max_quarters_per_command = 12 * 60 // 15  # Existing Bridge maximum.
            requested_ac = required_improvement / charge_eff
            for start_index in range(breach_index + 1):
                if blocked_prefix[start_index + 1] != blocked_prefix[start_index]:
                    continue
                end_limit = min(breach_index + 1, start_index + max_quarters_per_command)
                for end_index in range(start_index + 1, end_limit + 1):
                    if blocked_prefix[end_index] != blocked_prefix[start_index]:
                        break
                    if headroom_prefix[end_index] - headroom_prefix[start_index] < required_improvement - interval_epsilon:
                        continue
                    full_hours = .25 * (end_index - start_index)
                    effective_hours = full_hours - 2 / 60
                    if effective_hours <= 0:
                        continue
                    needed_power = requested_ac / effective_hours
                    if needed_power > max_charge_power_w / 1000 + 1e-9:
                        continue
                    power_kw = max(.1, ceil(needed_power * 100 - 1e-10) / 100)
                    if power_kw > max_charge_power_w / 1000 + 1e-9:
                        continue
                    # Score = sum(price_at_quarter * AC_energy_in_that_quarter).
                    # The first quarter loses 2 minutes; subsequent ones get
                    # their full 15 minutes under ONE physical setpoint.
                    price_weighted_hours = (cost_prefix[end_index] - cost_prefix[start_index]
                                            - prices_now[start_index] * 2 / 60)
                    cost = power_kw * price_weighted_hours
                    viable_windows.append((cost, -start_index, end_index,
                                           start_index, power_kw))
            if viable_windows:
                for _, _, end_index, start_index, power_kw in sorted(viable_windows):
                    trial_schedule = dict(safety_schedule)
                    for j in range(start_index, end_index):
                        seconds = 13 * 60 if j == start_index else 15 * 60
                        increment = power_kw * (seconds / 3600) * charge_eff
                        stamp = trace[j]["time"].isoformat()
                        trial_schedule[stamp] = trial_schedule.get(stamp, 0.0) + increment
                    trial_trace = _simulate_safety(trial_schedule)
                    if (trial_trace[breach_index]["stored_end_kwh"]
                            >= reserve_target_stored_kwh - interval_epsilon
                            and all(trial_trace[j]["stored_end_kwh"]
                                    >= trace[j]["stored_end_kwh"] - interval_epsilon
                                    for j in range(breach_index))):
                        safety_schedule = trial_schedule
                        break
                else:
                    # Existing source cheapest-quarter fallback remains active
                    # when no complete window can satisfy the physical need.
                    pass
                if safety_schedule != trace_schedule_before:
                    continue
        candidates = [
            index
            for index, item in enumerate(trace[: breach_index + 1])
            if item["import_price"] is not None
            and item["remaining_safety_stored_headroom_kwh"] > interval_epsilon
        ]
        # Same efficiency applies to every candidate, therefore import price is
        # sufficient for ordering. For equal prices prefer the latest window:
        # that preserves headroom for free solar and keeps the plan flexible.
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
            existing = safety_schedule.get(key, 0.0)

            trial_schedule = dict(safety_schedule)
            trial_schedule[key] = existing + maximum_add
            trial_trace = _simulate_safety(trial_schedule)
            maximum_improvement = (
                trial_trace[breach_index]["stored_end_kwh"] - breach_stored
            )
            if maximum_improvement <= interval_epsilon:
                continue

            allocation = maximum_add
            if maximum_improvement > required_improvement + interval_epsilon:
                low = 0.0
                high = maximum_add
                for _binary in range(18):
                    mid = (low + high) / 2.0
                    probe_schedule = dict(safety_schedule)
                    probe_schedule[key] = existing + mid
                    probe_trace = _simulate_safety(probe_schedule)
                    improvement = (
                        probe_trace[breach_index]["stored_end_kwh"] - breach_stored
                    )
                    if improvement >= required_improvement:
                        high = mid
                    else:
                        low = mid
                allocation = high

            if allocation <= interval_epsilon:
                continue
            safety_schedule[key] = existing + allocation
            allocation_made = True
            break

        if not allocation_made:
            break

    final_trace = _simulate_safety(safety_schedule)
    final_breaches = [
        item
        for item in final_trace
        if item["stored_end_kwh"] < reserve_target_stored_kwh - interval_epsilon
    ]
    selected_hours: list[dict[str, Any]] = []
    for item in final_trace:
        stored = item["actual_safety_stored_kwh"]
        if stored <= interval_epsilon:
            continue
        selected_hours.append(
            {
                "time": item["time"].isoformat(),
                "price": item["import_price"],
                "import_price": item["import_price"],
                "export_price": item["export_price"],
                "price_source": item["price_source"],
                "max_battery_energy_kwh": round(
                    item["maximum_safety_stored_kwh"], 3
                ),
                "candidate_battery_energy_kwh": round(stored, 3),
                "effective_delivered_cost": round(
                    item["import_price"] / roundtrip_eff, 6
                ),
            }
        )

    selected_safety_stored_kwh = sum(
        item["actual_safety_stored_kwh"] for item in final_trace
    )
    safety_charge_needed = bool(initial_breach_count)
    safety_schedule_sufficient = not final_breaches
    safety_first_breach_time = next(
        (
            item["time"]
            for item in initial_trace
            if item["stored_end_kwh"]
            < reserve_target_stored_kwh - interval_epsilon
        ),
        None,
    )
    current_safety_hour = next(
        (
            item
            for item in selected_hours
            if _parse_time(item.get("time")) == current_hour
        ),
        None,
    )

    discharge_possible = bool(
        valid
        and tradable_kwh is not None
        and tradable_kwh > _MIN_ENERGY_KWH
        and soc is not None
        and float(soc) > required_min_soc
    )

    solar_charge_delay = bool(
        valid
        and not safety_charge_needed
        and first_usable is not None
        and first_usable > now_utc
    )

    free_capacity_kwh = None
    if soc is not None:
        free_capacity_kwh = (
            capacity_kwh * max(0.0, 100.0 - float(soc)) / 100.0
        )

    # Financial pair search: buy in an earlier hour, use/sell in a later
    # more expensive hour. Cost is expressed per delivered kWh after both
    # charge and discharge losses.
    best_trade: dict[str, Any] | None = None
    for i, charge_row in enumerate(price_rows):
        if charge_row["time"].isoformat() in (protected_intervals or {}):
            continue
        effective_charge_cost = charge_row["import_price"] / roundtrip_eff
        for discharge_row in price_rows[i + 1:]:
            if discharge_row["time"].isoformat() in (protected_intervals or {}):
                continue
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
        best_trade is not None
        and best_trade["net_margin"] >= min_margin
        and not safety_charge_needed
    )

    current_is_best_charge = bool(
        best_trade is not None and best_trade["charge_time"] == current_hour
    )
    current_is_best_discharge = bool(
        best_trade is not None and best_trade["discharge_time"] == current_hour
    )

    trade_charge_candidate = bool(
        valid
        and not safety_charge_needed
        and free_capacity_kwh is not None
        and free_capacity_kwh > _MIN_ENERGY_KWH
        and trade_profitable
    )

    if not valid:
        decision = "wachten"
        reason = "Energiebalans is nog niet volledig geldig"
    elif safety_charge_needed:
        if current_safety_hour is not None:
            decision = "veiligheidsladen"
            reason = (
                "De 72-uurs SOC-route dreigt onder de 5%+7% planningsmarge te "
                "komen; het huidige uur is een geselecteerd goedkoop veiligheidslaadvenster"
            )
        elif selected_hours:
            decision = "wachten"
            reason = (
                "De 72-uurs SOC-route vraagt veiligheidslading; een goedkoper "
                "technisch haalbaar laadvenster ligt later"
            )
        else:
            decision = "wachten"
            reason = (
                "De 72-uurs SOC-route dreigt onder de planningsmarge te komen, "
                "maar de beschikbare laadvensters zijn technisch onvoldoende"
            )
    elif current_is_best_discharge and discharge_possible and trade_profitable:
        decision = "ontladen"
        reason = (
            "Huidig uur is financieel beste ontlaaduur en energie boven reserve "
            "is beschikbaar"
        )
    elif current_is_best_charge and trade_charge_candidate and not solar_charge_delay:
        decision = "handelsladen"
        reason = (
            "Huidig uur is financieel beste laaduur en verwachte netto marge "
            "overschrijdt de ingestelde minimum handelsmarge"
        )
    elif solar_charge_delay:
        decision = "wachten"
        reason = (
            "Voldoende batterijreserve tot bruikbare zon; netladen nu uitstellen"
        )
    elif trade_profitable:
        decision = "wachten"
        reason = (
            "Financieel rendabele handelscombinatie gevonden; beste laad- of "
            "ontlaaduur ligt later"
        )
    else:
        decision = "geen_actie"
        reason = (
            "Geen veiligheidslading nodig en geen handelscombinatie voldoet aan "
            "de ingestelde netto handelsmarge"
        )

    cheapest_preview = sorted(price_rows, key=lambda item: (item["import_price"], item["time"]))[:6]
    cheapest_preview = [
        {
            "time": row["time"].isoformat(),
            "price": row["import_price"],
            "import_price": row["import_price"],
            "export_price": row["export_price"],
            "price_source": row["price_source"],
        }
        for row in cheapest_preview
    ]

    return {
        "planner_preview_status": "ready" if valid else "waiting_for_energy_balance",
        "planner_preview_decision": decision,
        "planner_preview_reason": reason,
        "planner_preview_required_min_soc": round(required_min_soc, 1),
        "planner_preview_energy_above_reserve_kwh": (
            round(tradable_kwh, 3) if tradable_kwh is not None else None
        ),
        "planner_preview_safety_charge_needed": safety_charge_needed,
        "planner_preview_safety_charge_kwh": round(selected_safety_stored_kwh, 3),
        "planner_preview_safety_charge_hours": selected_hours,
        "planner_preview_safety_charge_hour_count": len(selected_hours),
        "planner_preview_safety_schedule_sufficient": safety_schedule_sufficient,
        "planner_preview_safety_reserve_target_soc": round(required_min_soc, 1),
        "planner_preview_safety_first_breach_time": (
            safety_first_breach_time.isoformat()
            if safety_first_breach_time is not None
            else None
        ),
        "planner_preview_safety_initial_breach_count": initial_breach_count,
        "planner_preview_safety_remaining_breach_count": len(final_breaches),
        "planner_preview_trade_charge_candidate": trade_charge_candidate,
        "planner_preview_discharge_possible": discharge_possible,
        "planner_preview_solar_charge_delay": solar_charge_delay,
        "planner_preview_first_usable_solar": (
            first_usable.isoformat() if first_usable is not None else None
        ),
        "planner_preview_price_min": price_min,
        "planner_preview_price_max": price_max,
        "planner_preview_price_spread": (
            round(price_spread, 6) if price_spread is not None else None
        ),
        "planner_preview_cheapest_hours": cheapest_preview,
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
        "planner_preview_best_charge_price": (
            round(best_trade["charge_price"], 6) if best_trade else None
        ),
        "planner_preview_best_discharge_time": (
            best_trade["discharge_time"].isoformat() if best_trade else None
        ),
        "planner_preview_best_discharge_price": (
            round(best_trade["discharge_price"], 6) if best_trade else None
        ),
        "planner_preview_effective_charge_cost": (
            round(best_trade["effective_charge_cost"], 6) if best_trade else None
        ),
        "planner_preview_expected_trade_margin": (
            round(best_trade["net_margin"], 6) if best_trade else None
        ),
        "planner_preview_replan_reason": "periodieke_observatieve_herberekening",
        "planner_preview_observational_only": True,
        "planner_preview_trading_execution_enabled": False,
        "planner_preview_losses_included": True,
        "planner_preview_assumed_max_charge_power_w": int(max_charge_power_w),
        "planner_preview_note": (
            "Alpha80 gebruikt de bestaande categorie veiligheidsladen voor de "
            "goedkoopste technisch haalbare energie om de rollende 72-uurs "
            "self_consumption-route boven 5%+7% planningsmarge te houden. Solar "
            "blijft eerste bron; er is geen extra laadtype of publieke sensor."
        ),
    }



def _hour_fraction(hour: datetime, now_utc: datetime, interval_minutes: int = 60) -> float:
    current_hour = _slot_start(now_utc, interval_minutes)
    if hour != current_hour:
        return 1.0
    elapsed = ((now_utc.minute % interval_minutes) + now_utc.second / 60.0) / interval_minutes
    return max(0.0, min(1.0, 1.0 - elapsed))



def build_72h_plan_preview(
    forecast: list[dict[str, Any]],
    energy_need: dict[str, Any],
    planner_preview: dict[str, Any],
    soc: float | None,
    charge_efficiency_percent: float,
    discharge_efficiency_percent: float,
    execution_buffer_percent: float = 2.0,
    max_charge_power_w: int = 3500,
    max_discharge_power_w: int = 3500,
    now: datetime | None = None,
    *, capacity_kwh: float = 7.2, min_soc_percent: float = 5.0,
    interval_minutes: int = 60,
    protected_intervals: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Build a sequential 72-hour battery plan preview.

    Alpha27 keeps the 72-hour planner observational only:
    - no plans are written to the three manual slots;
    - no Scheduler call is made;
    - no physical battery command is executed.
    """
    now_utc = (now or dt_util.utcnow()).astimezone(dt_util.UTC)
    _slot_start(now_utc, interval_minutes)
    current_hour = _slot_start(now_utc, interval_minutes)

    charge_eff = max(0.50, min(1.00, float(charge_efficiency_percent) / 100.0))
    discharge_eff = max(0.50, min(1.00, float(discharge_efficiency_percent) / 100.0))
    execution_buffer_percent = max(0.0, min(10.0, float(execution_buffer_percent)))
    interval_epsilon = _MIN_ENERGY_KWH * interval_minutes / 60.0

    if soc is None:
        return {
            "auto_plan_72h_status": "waiting_for_soc",
            "auto_plan_72h_valid": False,
            "auto_plan_72h_reason": "Geen geldige SOC beschikbaar",
            "auto_plan_72h_plan": [],
            "auto_plan_72h_count": 0,
            "auto_plan_72h_observational_only": True,
        }

    rows: list[dict[str, Any]] = []
    for raw in forecast:
        hour = _parse_time(raw.get("time"))
        if hour is None or hour < current_hour:
            continue
        rows.append(
            {
                "time": hour,
                "price": _as_float(raw.get("import_price")) if _as_float(raw.get("import_price")) is not None else _as_float(raw.get("price")),
                "import_price": _as_float(raw.get("import_price")) if _as_float(raw.get("import_price")) is not None else _as_float(raw.get("price")),
                "export_price": _as_float(raw.get("export_price")) if _as_float(raw.get("export_price")) is not None else (_as_float(raw.get("import_price")) if _as_float(raw.get("import_price")) is not None else _as_float(raw.get("price"))),
                "price_source": raw.get("price_source"),
                "import_price_source": raw.get("import_price_source") or raw.get("price_source"),
                "export_price_source": raw.get("export_price_source") or raw.get("price_source"),
                "solar_kwh": max(0.0, _as_float(raw.get("solar_kwh")) or 0.0),
                "home_kwh": max(0.0, _as_float(raw.get("home_consumption_kwh")) or 0.0),
            }
        )
    rows.sort(key=lambda item: item["time"])
    rows = rows[:72 * 60 // interval_minutes]

    if not rows:
        return {
            "auto_plan_72h_status": "waiting_for_forecast",
            "auto_plan_72h_valid": False,
            "auto_plan_72h_reason": "Geen bruikbare forecasturen beschikbaar",
            "auto_plan_72h_plan": [],
            "auto_plan_72h_count": 0,
            "auto_plan_72h_observational_only": True,
        }

    capacity = capacity_kwh
    start_soc = max(float(min_soc_percent), min(100.0, float(soc)))
    stored_kwh = capacity * start_soc / 100.0

    reserve_kwh = _as_float(energy_need.get("energy_need_safety_reserve_kwh")) or 0.0
    minimum_stored_kwh = capacity * float(min_soc_percent) / 100.0
    base_reserve_floor_kwh = minimum_stored_kwh + reserve_kwh
    base_reserve_floor_kwh = min(
        capacity,
        max(minimum_stored_kwh, base_reserve_floor_kwh),
    )
    execution_buffer_kwh = capacity * execution_buffer_percent / 100.0


    def _is_usable_solar(index: int) -> bool:
        if index < 0 or index >= len(rows):
            return False
        row = rows[index]
        return row["solar_kwh"] > 0 and row["solar_kwh"] >= row["home_kwh"]

    def _dynamic_reserve(index: int) -> tuple[float, float, datetime | None]:
        """Required stored energy from this hour until the next usable solar block.

        The usable-solar rule stays aligned with alpha21: the first of two
        consecutive hours where solar >= forecast home consumption.

        Home deficits are converted to required stored battery energy using the
        configured discharge efficiency. The fixed software safety reserve and
        5% hardware floor are then added.
        """
        if index >= len(rows):
            return base_reserve_floor_kwh, 0.0, None

        usable_index: int | None = None
        solar_span = 120 // interval_minutes
        for candidate in range(index, len(rows) - solar_span + 1):
            if all(_is_usable_solar(candidate + offset)
                   and rows[candidate + offset]["time"] == rows[candidate]["time"]
                       + timedelta(minutes=offset * interval_minutes)
                   for offset in range(solar_span)):
                usable_index = candidate
                break

        # The reserve floor is the existing 5% technical minimum plus the
        # configured software reserve. Forecast demand is diagnostic context and
        # must not become a fictitious physical hold in self_consumption.
        stop_index = usable_index if usable_index is not None else len(rows)
        net_home_need_kwh = 0.0

        for need_index in range(index, stop_index):
            need_row = rows[need_index]
            fraction = _hour_fraction(need_row["time"], now_utc, interval_minutes)
            net_home_need_kwh += max(
                0.0,
                need_row["home_kwh"] - need_row["solar_kwh"],
            ) * fraction

        floor_kwh = base_reserve_floor_kwh
        first_usable = rows[usable_index]["time"] if usable_index is not None else None
        return floor_kwh, net_home_need_kwh, first_usable

    def _execution_reserve(index: int) -> tuple[float, float, float, datetime | None]:
        """Return calculated reserve plus the alpha25 execution headroom."""
        floor_kwh, need_kwh, first_usable = _dynamic_reserve(index)
        execution_floor_kwh = min(capacity, floor_kwh + execution_buffer_kwh)
        return execution_floor_kwh, floor_kwh, need_kwh, first_usable

    safety_hours_raw = planner_preview.get("planner_preview_safety_charge_hours") or []
    safety_by_time: dict[str, float] = {}
    for item in safety_hours_raw:
        if not isinstance(item, dict):
            continue
        t = _parse_time(item.get("time"))
        if t is None:
            continue
        wanted = _as_float(item.get("candidate_battery_energy_kwh"))
        if wanted is None:
            wanted = _as_float(item.get("candidate_energy_kwh"))
        if wanted is not None and wanted > 0:
            safety_by_time[t.isoformat()] = wanted

    trade_profitable = bool(planner_preview.get("planner_preview_trade_profitable"))
    best_charge_time = _parse_time(planner_preview.get("planner_preview_best_charge_time"))
    best_discharge_time = _parse_time(planner_preview.get("planner_preview_best_discharge_time"))

    plan: list[dict[str, Any]] = []
    total_solar_charge = 0.0
    total_grid_safety_charge = 0.0
    total_grid_trade_charge = 0.0
    total_home_discharge = 0.0
    total_grid_trade_discharge = 0.0
    total_grid_import_for_home = 0.0
    total_solar_export = 0.0
    min_soc_seen = start_soc
    max_soc_seen = start_soc
    dynamic_reserve_min_soc = 100.0
    dynamic_reserve_max_soc = 0.0
    execution_reserve_min_soc = 100.0
    execution_reserve_max_soc = 0.0
    minimum_execution_headroom_soc = 100.0
    execution_buffer_breach_hours = 0

    # Reserve a future high-value discharge opportunity. This prevents battery
    # energy from being consumed too early by low-value home deficits.
    best_discharge_price = _as_float(planner_preview.get("planner_preview_best_discharge_price"))
    best_charge_price = _as_float(planner_preview.get("planner_preview_best_charge_price"))
    minimum_trade_margin = _as_float(planner_preview.get("planner_preview_minimum_trade_margin")) or 0.0

    def _matching_trade_intervals(anchor: datetime | None, price: float | None,
                                   field: str) -> set[datetime]:
        """Preserve one Alpha84 hourly trade quantum in native quarters.

        A uniquely priced quarter stays one quarter; four consecutive equal-
        priced quarters represent the original maximum one-hour buy or sell.
        The selected chronological pair and tie-breaks are never replaced.
        No averaging or blending of unequal native quarter prices occurs.
        """
        if anchor is None:
            return set()
        if interval_minutes == 60:
            return {anchor}
        result = set()
        indexed = {row["time"]: row for row in rows}
        for offset in range(60 // interval_minutes):
            stamp = anchor + timedelta(minutes=interval_minutes*offset)
            source = indexed.get(stamp)
            if (source is None or source[field] != price
                    or field == "import_price" and best_discharge_time is not None
                    and stamp >= best_discharge_time):
                break
            result.add(stamp)
        return result

    buy_intervals = _matching_trade_intervals(best_charge_time, best_charge_price,
                                               "import_price")
    sell_intervals = _matching_trade_intervals(best_discharge_time, best_discharge_price,
                                                "export_price")

    # Estimate how much future solar surplus can still charge the battery
    # between a candidate charge hour and the selected trade discharge hour.
    def future_solar_charge_potential(from_index: int, until_time: datetime | None) -> float:
        potential_input = 0.0
        for future in rows[from_index + 1:]:
            if until_time is not None and future["time"] > until_time:
                break
            future_solar = future["solar_kwh"]
            future_home = future["home_kwh"]
            potential_input += max(0.0, future_solar - future_home)
        return potential_input * charge_eff

    # Estimate the future home deficit before the best trade discharge hour.
    # Only deficits in more expensive hours than the candidate charge price
    # are allowed to use trade-reserved energy.
    def future_high_value_home_need(from_index: int, until_time: datetime | None, reference_price: float | None) -> float:
        need_output = 0.0
        for future in rows[from_index + 1:]:
            if until_time is not None and future["time"] > until_time:
                break
            future_price = future["import_price"]
            if reference_price is not None and future_price is not None and future_price <= reference_price:
                continue
            need_output += max(0.0, future["home_kwh"] - future["solar_kwh"])
        return need_output

    trade_energy_reserved_kwh = 0.0

    def _planned_dynamic_safety_charge_by_hour() -> dict[str, float]:
        """Pre-plan safety energy before each future execution-reserve deadline.

        Alpha27 fixes the timing edge found in alpha26: the reserve that applies
        *after* an hour must already be achievable by the end of that same hour.
        The previous implementation looked at the reserve at the start of the
        following hour, which could make a sharp reserve increase arrive one
        hour too late.

        For every local end-of-hour reserve peak we estimate how much stored
        energy will be available from the starting SOC and free solar. Only the
        remaining deficit is bought from the grid, allocated to the cheapest
        technically feasible hour(s) at or before the deadline.
        """
        planned: dict[str, float] = {}
        if not rows:
            return planned

        # A row's execution_floor_end is the requirement that must be met when
        # that row finishes. Therefore requirement index N uses reserve(N + 1),
        # but its charging deadline remains row N. This is the core alpha27 fix.
        reserve_requirements: list[tuple[int, float, datetime | None]] = []
        for idx, _row in enumerate(rows):
            execution_floor_end_kwh, _, _, next_solar = _execution_reserve(idx + 1)
            reserve_requirements.append((idx, execution_floor_end_kwh, next_solar))

        # Detect local end-of-hour reserve peaks tied to a demonstrable future
        # usable-solar block. Horizon-fallback hours deliberately do not create
        # artificial precharge demand.
        peaks: list[tuple[int, float, datetime]] = []
        for idx, floor_kwh, next_solar in reserve_requirements:
            if next_solar is None:
                continue
            prev_floor = reserve_requirements[idx - 1][1] if idx > 0 else base_reserve_floor_kwh
            next_floor = (
                reserve_requirements[idx + 1][1]
                if idx + 1 < len(reserve_requirements)
                else base_reserve_floor_kwh
            )
            if floor_kwh > prev_floor + interval_epsilon and floor_kwh >= next_floor - interval_epsilon:
                peaks.append((idx, floor_kwh, next_solar))

        for deadline_idx, required_floor_kwh, _next_solar in peaks:
            # Estimate stored energy available at the end of the deadline hour
            # from initial SOC + solar surplus + safety energy already allocated
            # for an earlier reserve peak. Discretionary discharge is ignored
            # here; the sequential planner later prevents discharge below the
            # execution reserve itself.
            estimated_stored = capacity * start_soc / 100.0
            for sim_idx in range(0, deadline_idx + 1):
                sim_row = rows[sim_idx]
                frac = _hour_fraction(sim_row["time"], now_utc, interval_minutes)
                protected_sim = (protected_intervals or {}).get(sim_row["time"].isoformat())
                if protected_sim is not None:
                    estimated_stored = max(minimum_stored_kwh, min(capacity,
                        estimated_stored + protected_sim['stored_delta_kwh']))
                else:
                    solar_surplus = max(
                        0.0,
                        (sim_row["solar_kwh"] - sim_row["home_kwh"]) * frac,
                    )
                    estimated_stored = min(
                        capacity,
                        estimated_stored + solar_surplus * charge_eff,
                    )
                key = sim_row["time"].isoformat()
                if key in planned:
                    estimated_stored = min(capacity, estimated_stored + planned[key])

            deficit_stored = max(0.0, required_floor_kwh - estimated_stored)
            if deficit_stored <= interval_epsilon:
                continue

            # Choose only hours that can physically contribute before the
            # deadline, ordered by price and then time. Planned values are stored
            # battery energy (after charge efficiency), matching the rest of the
            # planner's safety-allocation model.
            candidates: list[tuple[float, datetime, float]] = []
            for cand_idx in range(0, deadline_idx + 1):
                cand = rows[cand_idx]
                if cand["time"].isoformat() in (protected_intervals or {}):
                    continue
                price = cand["import_price"]
                if price is None:
                    continue
                fraction = _hour_fraction(cand["time"], now_utc, interval_minutes)

                # Safety precharge and solar charging share the same physical
                # charge-input ceiling.  The earlier alpha52 pre-planner used
                # the complete inverter charge limit for grid safety charging
                # and then the sequential planner correctly gave solar first
                # priority.  During a partially elapsed hour this could make the
                # pre-planner overestimate how much grid energy would actually
                # fit, leaving the final SOC just below the execution reserve.
                # Reserve only the grid-input headroom that remains after the
                # forecast solar surplus for this hour has taken its share.
                charge_input_limit = max_charge_power_w / 1000.0 * fraction * interval_minutes / 60
                solar_surplus_input = max(
                    0.0,
                    (cand["solar_kwh"] - cand["home_kwh"]) * fraction,
                )
                available_grid_input = max(0.0, charge_input_limit - solar_surplus_input)
                max_stored = available_grid_input * charge_eff
                if max_stored <= interval_epsilon:
                    continue
                candidates.append((price, cand["time"], max_stored))

            candidates.sort(key=lambda item: (item[0], item[1]))
            remaining = deficit_stored
            for _price, cand_time, max_stored in candidates:
                if remaining <= interval_epsilon:
                    break
                key = cand_time.isoformat()
                already = planned.get(key, 0.0)
                available = max(0.0, max_stored - already)
                if available <= interval_epsilon:
                    continue
                add = min(available, remaining)
                planned[key] = already + add
                remaining -= add

        return planned

    dynamic_safety_by_time = _planned_dynamic_safety_charge_by_hour()

    for index, row in enumerate(rows):
        hour = row["time"]
        fraction = _hour_fraction(hour, now_utc, interval_minutes)

        execution_floor_start_kwh, reserve_floor_start_kwh, reserve_need_start_kwh, next_usable_solar = _execution_reserve(index)
        execution_floor_end_kwh, reserve_floor_end_kwh, reserve_need_end_kwh, _ = _execution_reserve(index + 1)
        reserve_floor_start_soc = reserve_floor_start_kwh / capacity * 100.0
        reserve_floor_end_soc = reserve_floor_end_kwh / capacity * 100.0
        execution_floor_start_soc = execution_floor_start_kwh / capacity * 100.0
        execution_floor_end_soc = execution_floor_end_kwh / capacity * 100.0
        dynamic_reserve_min_soc = min(dynamic_reserve_min_soc, reserve_floor_end_soc)
        dynamic_reserve_max_soc = max(dynamic_reserve_max_soc, reserve_floor_start_soc)
        execution_reserve_min_soc = min(execution_reserve_min_soc, execution_floor_end_soc)
        execution_reserve_max_soc = max(execution_reserve_max_soc, execution_floor_start_soc)
        charge_input_limit = max_charge_power_w / 1000.0 * fraction * interval_minutes / 60
        discharge_output_limit = max_discharge_power_w / 1000.0 * fraction * interval_minutes / 60

        solar = row["solar_kwh"] * fraction
        home = row["home_kwh"] * fraction

        commitment = (protected_intervals or {}).get(hour.isoformat())
        solar_to_home = min(solar, home) if commitment is None else commitment.get('solar_to_home_kwh', 0.0)
        solar_surplus = max(0.0, solar - solar_to_home) if commitment is None else 0.0
        home_deficit = max(0.0, home - solar_to_home) if commitment is None else 0.0

        solar_charge_input = 0.0
        grid_safety_input = 0.0
        grid_trade_input = 0.0
        discharge_to_home = 0.0
        discharge_to_grid = 0.0
        grid_home = 0.0
        solar_export = 0.0

        available_charge_input = charge_input_limit

        # 1) Solar surplus charges first.
        if solar_surplus > interval_epsilon and stored_kwh < capacity - interval_epsilon:
            max_input_by_capacity = (capacity - stored_kwh) / charge_eff
            solar_charge_input = min(solar_surplus, available_charge_input, max_input_by_capacity)
            stored_added = solar_charge_input * charge_eff
            stored_kwh += stored_added
            available_charge_input -= solar_charge_input
            solar_surplus -= solar_charge_input

        solar_export = max(0.0, solar_surplus)

        # 2) Safety grid charge always has priority.
        # Alpha21/22 can already nominate a safety-charge hour. Alpha24.3 adds
        # a live 72-hour check: after solar charging, stored energy must be
        # sufficient for the dynamically calculated requirement from this hour
        # until the next usable solar block.
        planned_safety_target_stored = safety_by_time.get(hour.isoformat(), 0.0)
        dynamic_safety_target_stored = dynamic_safety_by_time.get(hour.isoformat(), 0.0)
        safety_target_stored = (max(
            planned_safety_target_stored,
            dynamic_safety_target_stored,
        ) if commitment is None else 0.0)

        if safety_target_stored > interval_epsilon and stored_kwh < capacity - interval_epsilon:
            max_input_by_capacity = (capacity - stored_kwh) / charge_eff
            requested_input = safety_target_stored / charge_eff
            grid_safety_input = min(
                requested_input,
                available_charge_input,
                max_input_by_capacity,
            )
            stored_kwh += grid_safety_input * charge_eff
            available_charge_input -= grid_safety_input

        # 3) Trade charging is blocked when expected solar can fill the same
        # free capacity before the selected sell hour (Solar Charge Delay).
        if (
            trade_profitable
            and best_charge_time is not None
            and hour in buy_intervals
            and available_charge_input > interval_epsilon
            and stored_kwh < capacity - interval_epsilon
        ):
            free_capacity_stored = max(0.0, capacity - stored_kwh)
            solar_fill_stored = future_solar_charge_potential(index, best_discharge_time)
            solar_charge_delay_active = solar_fill_stored >= max(0.0, free_capacity_stored - interval_epsilon)

            if not solar_charge_delay_active:
                # Only buy the capacity that is not expected to be filled by
                # free solar before the sell hour.
                required_trade_stored = max(0.0, free_capacity_stored - solar_fill_stored)

                # Keep trade charging economically meaningful. If the expected
                # sell price no longer clears the required margin, do not charge.
                effective_charge_cost = (
                    row["import_price"] / (charge_eff * discharge_eff)
                    if row["import_price"] is not None
                    else None
                )
                expected_margin = (
                    best_discharge_price - effective_charge_cost
                    if best_discharge_price is not None and effective_charge_cost is not None
                    else None
                )
                trade_allowed = expected_margin is not None and expected_margin >= minimum_trade_margin

                if trade_allowed and required_trade_stored > interval_epsilon:
                    max_input_by_capacity = free_capacity_stored / charge_eff
                    requested_input = required_trade_stored / charge_eff
                    grid_trade_input = min(
                        available_charge_input,
                        max_input_by_capacity,
                        requested_input,
                    )
                    stored_added = grid_trade_input * charge_eff
                    stored_kwh += stored_added
                    trade_energy_reserved_kwh += stored_added

        # 4) Normal self_consumption is physical reality. Household deficit
        # therefore uses the battery down to the technical device minimum.
        # Cheapest-energy safety charging is what keeps the *planned* route near
        # 5% + software reserve; reserve/trade intent may not fictitiously stop
        # normal home discharge.
        operational_floor = minimum_stored_kwh
        available_stored_above_floor = max(0.0, stored_kwh - operational_floor)
        max_output_from_storage = available_stored_above_floor * discharge_eff

        discharge_to_home = min(
            home_deficit,
            discharge_output_limit,
            max_output_from_storage,
        )
        if discharge_to_home > interval_epsilon:
            stored_used = discharge_to_home / discharge_eff
            stored_kwh -= stored_used
            home_deficit -= discharge_to_home
            trade_energy_reserved_kwh = max(
                0.0,
                trade_energy_reserved_kwh - stored_used,
            )

        grid_home = max(0.0, home_deficit)

        # 5) At the selected best sell hour, discharge only energy above the
        # operational reserve. Home has priority, remainder may go to the grid.
        if (
            trade_profitable
            and best_discharge_time is not None
            and hour in sell_intervals
        ):
            remaining_output_limit = max(0.0, discharge_output_limit - discharge_to_home)
            available_stored_above_reserve = max(
                0.0,
                stored_kwh - execution_floor_end_kwh,
            )
            max_trade_output = available_stored_above_reserve * discharge_eff
            discharge_to_grid = min(remaining_output_limit, max_trade_output)
            if discharge_to_grid > interval_epsilon:
                stored_used = discharge_to_grid / discharge_eff
                stored_kwh -= stored_used
                trade_energy_reserved_kwh = max(
                    0.0,
                    trade_energy_reserved_kwh - stored_used,
                )

        if commitment is not None:
            # Plan72-only projected manual/due/active energy was entered into
            # the allocation *before* candidate selection. Source actions are
            # not created in this interval. The native Plan72 route, not this
            # preview, remains authoritative for the resulting SOC and flows.
            stored_kwh += commitment['stored_delta_kwh']
            solar_charge_input = commitment.get('charge_from_solar_kwh', 0.0)
            discharge_to_home = commitment.get('discharge_to_home_kwh', 0.0)
            grid_home = commitment.get('grid_import_for_home_kwh', 0.0)
            solar_export = commitment.get('solar_export_kwh', 0.0)
            trade_energy_reserved_kwh = max(0.0, trade_energy_reserved_kwh
                - (commitment.get('discharge_to_grid_kwh', 0.0)
                   + discharge_to_home) / discharge_eff)
        stored_kwh = max(
            capacity * float(min_soc_percent) / 100.0,
            min(capacity, stored_kwh),
        )
        soc_start = plan[-1]["soc_end"] if plan else start_soc
        soc_end = stored_kwh / capacity * 100.0
        min_soc_seen = min(min_soc_seen, soc_end)
        max_soc_seen = max(max_soc_seen, soc_end)
        execution_headroom_soc = soc_end - float(min_soc_percent)
        minimum_execution_headroom_soc = min(
            minimum_execution_headroom_soc,
            execution_headroom_soc,
        )
        # The higher execution reserve applies to explicit external discharge,
        # not to ordinary self_consumption. Only a grid-discharge action may
        # violate that control buffer.
        if (
            discharge_to_grid > interval_epsilon
            and soc_end - execution_floor_end_soc < -0.05
        ):
            execution_buffer_breach_hours += 1

        action_parts: list[str] = []
        if grid_safety_input > interval_epsilon:
            action_parts.append("veiligheidsladen")
        if grid_trade_input > interval_epsilon:
            action_parts.append("handelsladen")
        if solar_charge_input > interval_epsilon:
            action_parts.append("zonneladen")
        if discharge_to_home > interval_epsilon:
            action_parts.append("woning_ontladen")
        if discharge_to_grid > interval_epsilon:
            action_parts.append("handel_ontladen")
        if not action_parts:
            action_parts.append("geen_actie")

        total_solar_charge += solar_charge_input
        total_grid_safety_charge += grid_safety_input
        total_grid_trade_charge += grid_trade_input
        total_home_discharge += discharge_to_home
        total_grid_trade_discharge += discharge_to_grid
        total_grid_import_for_home += grid_home
        total_solar_export += solar_export

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
                "solar_export_kwh": round(solar_export, 3),
                "soc_start": round(float(soc_start), 1),
                "soc_end": round(soc_end, 1),
                "reserve_floor_soc": round(reserve_floor_end_soc, 1),
                "reserve_floor_start_soc": round(reserve_floor_start_soc, 1),
                "execution_reserve_floor_soc": round(execution_floor_end_soc, 1),
                "execution_reserve_floor_start_soc": round(execution_floor_start_soc, 1),
                "execution_buffer_percent": round(execution_buffer_percent, 1),
                "execution_headroom_soc": round(execution_headroom_soc, 1),
                "dynamic_need_until_solar_kwh": round(reserve_need_start_kwh, 3),
                "dynamic_need_after_hour_kwh": round(reserve_need_end_kwh, 3),
                "next_usable_solar": (
                    next_usable_solar.isoformat()
                    if next_usable_solar is not None
                    else None
                ),
                "solar_horizon_complete": next_usable_solar is not None,
                "trade_reserved_kwh": round(trade_energy_reserved_kwh, 3),
                "action": "+".join(action_parts),
                "observational_only": True,
            }
        )

    end_soc = plan[-1]["soc_end"] if plan else start_soc

    return {
        "auto_plan_72h_status": "ready",
        "auto_plan_72h_valid": True,
        "auto_plan_72h_reason": (
            "72-uurs planpreview berekend; solar heeft voorrang en bestaande "
            "veiligheidslading koopt vóór een verwachte 5%+7%-margebreuk de "
            "goedkoopste technisch haalbare netenergie"
        ),
        "auto_plan_72h_plan": plan,
        "auto_plan_72h_count": len(plan),
        "auto_plan_72h_start": plan[0]["time"] if plan else None,
        "auto_plan_72h_end": plan[-1]["time"] if plan else None,
        "auto_plan_72h_start_soc": round(start_soc, 1),
        "auto_plan_72h_end_soc": round(float(end_soc), 1),
        "auto_plan_72h_min_soc": round(min_soc_seen, 1),
        "auto_plan_72h_max_soc": round(max_soc_seen, 1),
        "auto_plan_72h_reserve_floor_soc": (
            round(plan[0]["reserve_floor_start_soc"], 1) if plan else None
        ),
        "auto_plan_72h_dynamic_reserve_min_soc": round(dynamic_reserve_min_soc, 1),
        "auto_plan_72h_dynamic_reserve_max_soc": round(dynamic_reserve_max_soc, 1),
        "auto_plan_72h_execution_buffer_percent": round(execution_buffer_percent, 1),
        "auto_plan_72h_max_charge_power_w": int(max_charge_power_w),
        "auto_plan_72h_max_discharge_power_w": int(max_discharge_power_w),
        "auto_plan_72h_execution_reserve_floor_soc": (
            round(plan[0]["execution_reserve_floor_start_soc"], 1) if plan else None
        ),
        "auto_plan_72h_execution_reserve_min_soc": round(execution_reserve_min_soc, 1),
        "auto_plan_72h_execution_reserve_max_soc": round(execution_reserve_max_soc, 1),
        "auto_plan_72h_min_execution_headroom_soc": round(minimum_execution_headroom_soc, 1),
        "auto_plan_72h_execution_buffer_breach_hours": execution_buffer_breach_hours,
        "auto_plan_72h_execution_buffer_safe": execution_buffer_breach_hours == 0,
        "auto_plan_72h_solar_horizon_complete": all(
            item.get("solar_horizon_complete", False) for item in plan
        ),
        "auto_plan_72h_solar_horizon_incomplete_hours": sum(
            1 for item in plan if not item.get("solar_horizon_complete", False)
        ),
        "auto_plan_72h_solar_charge_kwh": round(total_solar_charge, 3),
        "auto_plan_72h_grid_safety_charge_kwh": round(total_grid_safety_charge, 3),
        "auto_plan_72h_grid_trade_charge_kwh": round(total_grid_trade_charge, 3),
        "auto_plan_72h_home_discharge_kwh": round(total_home_discharge, 3),
        "auto_plan_72h_grid_trade_discharge_kwh": round(total_grid_trade_discharge, 3),
        "auto_plan_72h_grid_import_for_home_kwh": round(total_grid_import_for_home, 3),
        "auto_plan_72h_solar_export_kwh": round(total_solar_export, 3),
        "auto_plan_72h_trade_charge_stored_kwh": round(total_grid_trade_charge * charge_eff, 3),
        "auto_plan_72h_charge_efficiency_percent": round(charge_eff * 100.0, 1),
        "auto_plan_72h_discharge_efficiency_percent": round(discharge_eff * 100.0, 1),
        "auto_plan_72h_observational_only": True,
        "auto_plan_72h_execution_enabled": False,
        "auto_plan_72h_note": (
            "Alpha80 houdt de publieke laadcategorieën compact. Solar blijft "
            "eerste bron; goedkope noodzakelijke netbijlading gebruikt uitsluitend "
            "veiligheidsladen. Normale self_consumption ontlaadt fysiek tot 5% "
            "wanneer de geplande 12%-marge technisch niet haalbaar is."
        ),
    }
