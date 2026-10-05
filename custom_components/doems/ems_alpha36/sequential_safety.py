from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from ..ems_alpha76.const import (
    DEFAULT_AUTO_EXECUTION_BUFFER_PERCENT,
    DEFAULT_BATTERY_CAPACITY_KWH,
    MIN_SOC_PERCENT,
)

_MIN_ENERGY_KWH = 0.01
_SAFETY_TOL_KWH = 1e-6


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


def build_72h_plan_preview_alpha36_sequential_safety(
    forecast: list[dict[str, Any]],
    energy_need: dict[str, Any],
    planner_preview: dict[str, Any],
    soc: float | None,
    charge_efficiency_percent: float,
    discharge_efficiency_percent: float,
    execution_buffer_percent: float = DEFAULT_AUTO_EXECUTION_BUFFER_PERCENT,
    max_charge_power_w: int = 3500,
    max_discharge_power_w: int = 3500,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build Alpha36 safety by seeding Alpha35 replay with Alpha80 commitments.

    The Alpha80 Preview safety schedule is treated as the economic minimum.
    The sequential Alpha35 replay may add safety energy when required to satisfy
    the stricter execution-reserve path, but it never discards an accepted
    Alpha80 safety commitment merely because the older Alpha35 dynamic reserve
    would have required less energy.

    The planner remains observational at this layer:
    - no plans are written to the three manual slots;
    - no Scheduler call is made;
    - no physical battery command is executed.
    """
    now_utc = (now or dt_util.utcnow()).astimezone(dt_util.UTC)
    current_hour = now_utc.replace(minute=0, second=0, microsecond=0)

    charge_eff = max(0.50, min(1.00, float(charge_efficiency_percent) / 100.0))
    discharge_eff = max(0.50, min(1.00, float(discharge_efficiency_percent) / 100.0))
    execution_buffer_percent = max(0.0, min(10.0, float(execution_buffer_percent)))

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
    rows = rows[:72]

    if not rows:
        return {
            "auto_plan_72h_status": "waiting_for_forecast",
            "auto_plan_72h_valid": False,
            "auto_plan_72h_reason": "Geen bruikbare forecasturen beschikbaar",
            "auto_plan_72h_plan": [],
            "auto_plan_72h_count": 0,
            "auto_plan_72h_observational_only": True,
        }

    capacity = DEFAULT_BATTERY_CAPACITY_KWH
    start_soc = max(float(MIN_SOC_PERCENT), min(100.0, float(soc)))
    stored_kwh = capacity * start_soc / 100.0

    reserve_kwh = _as_float(energy_need.get("energy_need_safety_reserve_kwh")) or 0.0
    minimum_stored_kwh = capacity * float(MIN_SOC_PERCENT) / 100.0
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

    def _future_safety_need(index: int) -> tuple[float, float, datetime | None]:
        """Return the future safety target without turning it into a hold floor.

        Alpha38 Design C separates the fixed operational reserve from the
        forward-looking energy requirement.  The latter remains authoritative
        for precharge deadlines and reachability, but it no longer raises
        reserve_floor_soc or the ordinary execution floor.
        """
        if index >= len(rows):
            return base_reserve_floor_kwh, 0.0, None

        usable_index: int | None = None
        for candidate in range(index, len(rows) - 1):
            if _is_usable_solar(candidate) and _is_usable_solar(candidate + 1):
                usable_index = candidate
                break

        if usable_index is None:
            return base_reserve_floor_kwh, 0.0, None

        net_home_need_kwh = 0.0
        for need_index in range(index, usable_index):
            need_row = rows[need_index]
            fraction = _hour_fraction(need_row["time"], now_utc)
            net_home_need_kwh += max(
                0.0,
                need_row["home_kwh"] - need_row["solar_kwh"],
            ) * fraction

        stored_need_kwh = net_home_need_kwh / discharge_eff
        safety_target_kwh = min(
            capacity,
            max(
                base_reserve_floor_kwh,
                base_reserve_floor_kwh + stored_need_kwh,
            ),
        )
        return safety_target_kwh, net_home_need_kwh, rows[usable_index]["time"]

    def _dynamic_reserve(index: int) -> tuple[float, float, datetime | None]:
        """Return fixed operational reserve plus forward-looking diagnostics."""
        _target_kwh, need_kwh, first_usable = _future_safety_need(index)
        return base_reserve_floor_kwh, need_kwh, first_usable

    def _execution_reserve(index: int) -> tuple[float, float, float, datetime | None]:
        """Return the fixed reserve plus the small execution headroom."""
        floor_kwh, need_kwh, first_usable = _dynamic_reserve(index)
        execution_floor_kwh = min(capacity, floor_kwh + execution_buffer_kwh)
        return execution_floor_kwh, floor_kwh, need_kwh, first_usable

    def _safety_deadline_floor(index: int) -> tuple[float, float, datetime | None]:
        """Return future safety target used only for precharge reachability."""
        target_kwh, need_kwh, first_usable = _future_safety_need(index)
        return min(capacity, target_kwh + execution_buffer_kwh), need_kwh, first_usable

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

    def _build_sequential_safety_plan() -> dict[str, Any]:
        """Replay one authoritative safety plan against the actual SOC path.

        This is the second explicitly authorized DOEMS exception to Alpha76.
        The original Alpha76 pre-estimator restarts each future deadline from
        the original start SOC and therefore can forget intervening home
        discharge. The replay below uses the same hour sequence continuously,
        protects accepted safety energy until its deadline and chooses the
        cheapest technically useful charge hours at or before each deadline.
        """
        # Alpha36 best-of-both rule: start with the Alpha80 cheapest-energy
        # safety commitments. These values are stored battery kWh and therefore
        # use the same unit as the Alpha35 sequential schedule. The replay caps
        # them by real charge headroom/capacity; later reserve checks may add
        # extra bridge/safety energy where the stricter Alpha35 path requires it.
        planned: dict[str, float] = dict(safety_by_time)
        commitments: list[dict[str, Any]] = []
        replay_count = 0

        precharge_floors: list[float] = []
        for reserve_index in range(len(rows) + 1):
            safety_deadline_floor, _, _ = _safety_deadline_floor(reserve_index)
            precharge_floors.append(safety_deadline_floor)

        # Backward reachability: existing energy may not be spent when maximum
        # charging power would no longer restore the coming execution reserve.
        for reserve_index in range(len(rows) - 1, -1, -1):
            fraction = _hour_fraction(rows[reserve_index]["time"], now_utc)
            max_stored = max_charge_power_w / 1000.0 * fraction * charge_eff
            precharge_floors[reserve_index] = max(
                precharge_floors[reserve_index],
                precharge_floors[reserve_index + 1] - max_stored,
            )

        def replay(length: int | None = None) -> dict[str, Any]:
            nonlocal replay_count
            replay_count += 1
            limit = len(rows) if length is None else max(0, min(len(rows), length))
            stored = capacity * start_soc / 100.0
            held_safety: list[tuple[int, float]] = []
            output: list[dict[str, Any]] = []

            commitments_by_time: dict[str, list[dict[str, Any]]] = {}
            for item in commitments:
                commitments_by_time.setdefault(str(item["time"]), []).append(item)

            for sim_index, sim_row in enumerate(rows[:limit]):
                held_safety = [
                    (deadline, energy)
                    for deadline, energy in held_safety
                    if deadline > sim_index
                ]
                fraction = _hour_fraction(sim_row["time"], now_utc)
                charge_input_limit = max_charge_power_w / 1000.0 * fraction
                discharge_output_limit = max_discharge_power_w / 1000.0 * fraction
                execution_floor_end, _, _, _ = _execution_reserve(sim_index + 1)
                protected_floor = max(
                    execution_floor_end,
                    precharge_floors[sim_index + 1],
                )

                solar = sim_row["solar_kwh"] * fraction
                home = sim_row["home_kwh"] * fraction
                solar_to_home = min(solar, home)
                solar_surplus = max(0.0, solar - solar_to_home)
                home_deficit = max(0.0, home - solar_to_home)

                available_charge_input = charge_input_limit
                solar_charge_input = min(
                    solar_surplus,
                    available_charge_input,
                    max(0.0, (capacity - stored) / charge_eff),
                )
                stored += solar_charge_input * charge_eff
                available_charge_input -= solar_charge_input

                key = sim_row["time"].isoformat()
                wanted_safety_stored = max(0.0, planned.get(key, 0.0))
                grid_safety_input = 0.0
                if wanted_safety_stored > _SAFETY_TOL_KWH and available_charge_input > _SAFETY_TOL_KWH:
                    grid_safety_input = min(
                        wanted_safety_stored / charge_eff,
                        available_charge_input,
                        max(0.0, (capacity - stored) / charge_eff),
                    )
                    stored += grid_safety_input * charge_eff
                    available_charge_input -= grid_safety_input

                for commitment in commitments_by_time.get(key, []):
                    deadline = int(commitment["deadline_index"])
                    if deadline > sim_index and wanted_safety_stored > _SAFETY_TOL_KWH:
                        accepted = (
                            grid_safety_input
                            * charge_eff
                            * float(commitment["stored_battery_kwh"])
                            / wanted_safety_stored
                        )
                        held_safety.append((deadline, accepted))

                safety_reserved_kwh = sum(energy for _, energy in held_safety)
                remaining_safety_headroom = min(
                    available_charge_input * charge_eff,
                    max(0.0, capacity - stored),
                )

                operational_floor = min(
                    capacity,
                    protected_floor + safety_reserved_kwh,
                )
                available_stored_above_floor = max(0.0, stored - operational_floor)
                max_output_from_storage = available_stored_above_floor * discharge_eff
                discharge_to_home = min(
                    home_deficit,
                    discharge_output_limit,
                    max_output_from_storage,
                )
                if discharge_to_home > _SAFETY_TOL_KWH:
                    stored -= discharge_to_home / discharge_eff

                stored = max(
                    capacity * float(MIN_SOC_PERCENT) / 100.0,
                    min(capacity, stored),
                )
                output.append(
                    {
                        "time": key,
                        "end_stored_kwh": stored,
                        "accepted_safety_stored_kwh": grid_safety_input * charge_eff,
                        "grid_safety_input_kwh": grid_safety_input,
                        "remaining_safety_charge_stored_kwh": remaining_safety_headroom,
                    }
                )
            return {"rows": output}

        result = replay()
        for deadline_index in range(len(rows)):
            required_floor, _, _ = _safety_deadline_floor(deadline_index + 1)
            if (
                result["rows"][deadline_index]["end_stored_kwh"] + _SAFETY_TOL_KWH
                >= required_floor
            ):
                continue

            candidates = sorted(
                range(deadline_index + 1),
                key=lambda idx: (
                    rows[idx]["import_price"]
                    if rows[idx]["import_price"] is not None
                    else float("inf"),
                    -rows[idx]["time"].timestamp(),
                ),
            )
            changed = False
            for candidate_index in candidates:
                current = result["rows"][deadline_index]["end_stored_kwh"]
                deficit = required_floor - current
                if deficit <= _SAFETY_TOL_KWH:
                    break
                available = result["rows"][candidate_index][
                    "remaining_safety_charge_stored_kwh"
                ]
                if available <= _SAFETY_TOL_KWH:
                    continue

                key = rows[candidate_index]["time"].isoformat()
                previous = planned.get(key, 0.0)
                addition = min(deficit, available)
                planned[key] = previous + addition
                commitment = {
                    "time": key,
                    "deadline_index": deadline_index,
                    "deadline": (
                        rows[deadline_index]["time"] + timedelta(hours=1)
                    ).isoformat(),
                    "stored_battery_kwh": addition,
                }
                commitments.append(commitment)

                trial = replay(deadline_index + 1)
                achieved = trial["rows"][deadline_index]["end_stored_kwh"]
                if achieved <= current + _SAFETY_TOL_KWH:
                    commitments.pop()
                    if previous > 0.0:
                        planned[key] = previous
                    else:
                        planned.pop(key, None)
                    continue

                result = trial
                changed = True

            if changed:
                result = replay()

        # Normalize requested schedule to energy the replay actually accepted.
        actual_by_time = {
            item["time"]: item["accepted_safety_stored_kwh"]
            for item in result["rows"]
        }
        for commitment in commitments:
            key = str(commitment["time"])
            requested = planned.get(key, 0.0)
            ratio = (
                min(1.0, actual_by_time.get(key, 0.0) / requested)
                if requested > _SAFETY_TOL_KWH
                else 0.0
            )
            commitment["stored_battery_kwh"] *= ratio
        planned = {
            key: min(value, actual_by_time.get(key, 0.0))
            for key, value in planned.items()
            if actual_by_time.get(key, 0.0) > _SAFETY_TOL_KWH
        }
        result = replay()

        breaches: list[dict[str, Any]] = []
        for breach_index, item in enumerate(result["rows"]):
            required_floor, _, _, _ = _execution_reserve(breach_index + 1)
            shortfall = required_floor - item["end_stored_kwh"]
            if shortfall > _SAFETY_TOL_KWH:
                breaches.append(
                    {
                        "index": breach_index,
                        "time": rows[breach_index]["time"].isoformat(),
                        "required_soc_percent": round(
                            required_floor / capacity * 100.0, 1
                        ),
                        "projected_soc_percent": round(
                            item["end_stored_kwh"] / capacity * 100.0, 1
                        ),
                        "shortfall_battery_kwh": round(shortfall, 6),
                    }
                )

        return {
            "schedule": planned,
            "commitments": commitments,
            "precharge_floors": precharge_floors,
            "simulation": result,
            "replay_count": replay_count,
            "requested_stored_kwh": round(sum(planned.values()), 6),
            "accepted_stored_kwh": round(
                sum(item["accepted_safety_stored_kwh"] for item in result["rows"]),
                6,
            ),
            "accepted_grid_input_kwh": round(
                sum(item["grid_safety_input_kwh"] for item in result["rows"]),
                6,
            ),
            "breaches": breaches,
        }

    sequential_safety = _build_sequential_safety_plan()
    dynamic_safety_by_time = sequential_safety["schedule"]
    precharge_floors = sequential_safety["precharge_floors"]
    safety_commitments_by_time: dict[str, list[dict[str, Any]]] = {}
    for commitment in sequential_safety["commitments"]:
        safety_commitments_by_time.setdefault(str(commitment["time"]), []).append(
            commitment
        )
    held_safety: list[tuple[int, float]] = []
    upstream_safety_advice_stored_kwh = round(sum(safety_by_time.values()), 6)

    for index, row in enumerate(rows):
        held_safety = [
            (deadline, energy)
            for deadline, energy in held_safety
            if deadline > index
        ]
        hour = row["time"]
        fraction = _hour_fraction(hour, now_utc)

        execution_floor_start_kwh, reserve_floor_start_kwh, reserve_need_start_kwh, next_usable_solar = _execution_reserve(index)
        execution_floor_end_kwh, reserve_floor_end_kwh, reserve_need_end_kwh, _ = _execution_reserve(index + 1)
        safety_target_start_kwh, _, _ = _future_safety_need(index)
        safety_target_end_kwh, _, _ = _future_safety_need(index + 1)
        reserve_floor_start_soc = reserve_floor_start_kwh / capacity * 100.0
        reserve_floor_end_soc = reserve_floor_end_kwh / capacity * 100.0
        execution_floor_start_soc = execution_floor_start_kwh / capacity * 100.0
        execution_floor_end_soc = execution_floor_end_kwh / capacity * 100.0
        dynamic_reserve_min_soc = min(dynamic_reserve_min_soc, reserve_floor_end_soc)
        dynamic_reserve_max_soc = max(dynamic_reserve_max_soc, reserve_floor_start_soc)
        execution_reserve_min_soc = min(execution_reserve_min_soc, execution_floor_end_soc)
        execution_reserve_max_soc = max(execution_reserve_max_soc, execution_floor_start_soc)
        charge_input_limit = max_charge_power_w / 1000.0 * fraction
        discharge_output_limit = max_discharge_power_w / 1000.0 * fraction

        solar = row["solar_kwh"] * fraction
        home = row["home_kwh"] * fraction

        solar_to_home = min(solar, home)
        solar_surplus = max(0.0, solar - solar_to_home)
        home_deficit = max(0.0, home - solar_to_home)

        solar_charge_input = 0.0
        grid_safety_input = 0.0
        grid_trade_input = 0.0
        discharge_to_home = 0.0
        discharge_to_grid = 0.0
        grid_home = 0.0
        solar_export = 0.0

        available_charge_input = charge_input_limit

        # 1) Solar surplus charges first.
        if solar_surplus > _MIN_ENERGY_KWH and stored_kwh < capacity - _MIN_ENERGY_KWH:
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
        safety_target_stored = dynamic_safety_target_stored

        if safety_target_stored > _MIN_ENERGY_KWH and stored_kwh < capacity - _MIN_ENERGY_KWH:
            max_input_by_capacity = (capacity - stored_kwh) / charge_eff
            requested_input = safety_target_stored / charge_eff
            grid_safety_input = min(
                requested_input,
                available_charge_input,
                max_input_by_capacity,
            )
            stored_kwh += grid_safety_input * charge_eff
            available_charge_input -= grid_safety_input

        for commitment in safety_commitments_by_time.get(hour.isoformat(), []):
            deadline = int(commitment["deadline_index"])
            if deadline > index and safety_target_stored > _SAFETY_TOL_KWH:
                accepted = (
                    grid_safety_input
                    * charge_eff
                    * float(commitment["stored_battery_kwh"])
                    / safety_target_stored
                )
                held_safety.append((deadline, accepted))
        safety_reserved_kwh = sum(energy for _, energy in held_safety)

        # 3) Trade charging is blocked when expected solar can fill the same
        # free capacity before the selected sell hour (Solar Charge Delay).
        if (
            trade_profitable
            and best_charge_time is not None
            and hour == best_charge_time
            and available_charge_input > _MIN_ENERGY_KWH
            and stored_kwh < capacity - _MIN_ENERGY_KWH
        ):
            free_capacity_stored = max(0.0, capacity - stored_kwh)
            solar_fill_stored = future_solar_charge_potential(index, best_discharge_time)
            solar_charge_delay_active = solar_fill_stored >= max(0.0, free_capacity_stored - _MIN_ENERGY_KWH)

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

                if trade_allowed and required_trade_stored > _MIN_ENERGY_KWH:
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

        # 4) Home deficit uses battery only when doing so does not consume
        # energy reserved for a later, more valuable trade discharge.
        protected_floor = max(
            execution_floor_end_kwh,
            precharge_floors[index + 1],
        )
        operational_floor = min(
            capacity,
            protected_floor + safety_reserved_kwh + trade_energy_reserved_kwh,
        )

        available_stored_above_floor = max(0.0, stored_kwh - operational_floor)
        max_output_from_storage = available_stored_above_floor * discharge_eff

        # Prefer battery for home use when the current price is at least as high
        # as the best buy price plus the requested trade margin, or when there is
        # no active future trade reservation.
        current_price = row["import_price"]
        threshold_price = None
        if best_charge_price is not None:
            threshold_price = best_charge_price / (charge_eff * discharge_eff) + minimum_trade_margin

        allow_home_discharge = trade_energy_reserved_kwh <= _MIN_ENERGY_KWH
        if (
            current_price is not None
            and threshold_price is not None
            and current_price >= threshold_price
        ):
            allow_home_discharge = True

        if allow_home_discharge:
            discharge_to_home = min(
                home_deficit,
                discharge_output_limit,
                max_output_from_storage,
            )
            if discharge_to_home > _MIN_ENERGY_KWH:
                stored_used = discharge_to_home / discharge_eff
                stored_kwh -= stored_used
                home_deficit -= discharge_to_home

                # If high-value home use happens before the selected trade hour,
                # it can consume part of the trade reservation because it creates
                # equal or better economic value than later grid export.
                if trade_energy_reserved_kwh > _MIN_ENERGY_KWH and current_price is not None:
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
            and hour == best_discharge_time
        ):
            remaining_output_limit = max(0.0, discharge_output_limit - discharge_to_home)
            available_stored_above_reserve = max(
                0.0,
                stored_kwh - protected_floor - safety_reserved_kwh,
            )
            max_trade_output = available_stored_above_reserve * discharge_eff
            discharge_to_grid = min(remaining_output_limit, max_trade_output)
            if discharge_to_grid > _MIN_ENERGY_KWH:
                stored_used = discharge_to_grid / discharge_eff
                stored_kwh -= stored_used
                trade_energy_reserved_kwh = max(
                    0.0,
                    trade_energy_reserved_kwh - stored_used,
                )

        stored_kwh = max(
            capacity * float(MIN_SOC_PERCENT) / 100.0,
            min(capacity, stored_kwh),
        )
        soc_start = plan[-1]["soc_end"] if plan else start_soc
        soc_end = stored_kwh / capacity * 100.0
        min_soc_seen = min(min_soc_seen, soc_end)
        max_soc_seen = max(max_soc_seen, soc_end)
        execution_headroom_soc = soc_end - execution_floor_end_soc
        minimum_execution_headroom_soc = min(minimum_execution_headroom_soc, execution_headroom_soc)
        if execution_headroom_soc < -0.05:
            execution_buffer_breach_hours += 1

        action_parts: list[str] = []
        if grid_safety_input > _MIN_ENERGY_KWH:
            action_parts.append("veiligheidsladen")
        if grid_trade_input > _MIN_ENERGY_KWH:
            action_parts.append("handelsladen")
        if solar_charge_input > _MIN_ENERGY_KWH:
            action_parts.append("zonneladen")
        if discharge_to_home > _MIN_ENERGY_KWH:
            action_parts.append("woning_ontladen")
        if discharge_to_grid > _MIN_ENERGY_KWH:
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
                "safety_reserved_kwh": round(safety_reserved_kwh, 3),
                "precharge_protection_soc": round(
                    protected_floor / capacity * 100.0, 1
                ),
                "safety_target_soc": round(
                    safety_target_end_kwh / capacity * 100.0, 1
                ),
                "safety_target_start_soc": round(
                    safety_target_start_kwh / capacity * 100.0, 1
                ),
                "action": "+".join(action_parts),
                "observational_only": True,
            }
        )

    end_soc = plan[-1]["soc_end"] if plan else start_soc

    safety_deadlines_safe = not sequential_safety["breaches"]
    execution_buffer_safe = execution_buffer_breach_hours == 0 and safety_deadlines_safe
    first_execution_breach = next(
        (
            {
                "index": idx,
                "time": item["time"],
                "soc_percent": item["soc_end"],
                "required_soc_percent": item["execution_reserve_floor_soc"],
                "shortfall_battery_kwh": round(
                    max(
                        0.0,
                        (
                            item["execution_reserve_floor_soc"] - item["soc_end"]
                        )
                        / 100.0
                        * capacity,
                    ),
                    6,
                ),
            }
            for idx, item in enumerate(plan)
            if item["soc_end"] + 0.05 < item["execution_reserve_floor_soc"]
        ),
        None,
    )

    return {
        "auto_plan_72h_status": "ready" if execution_buffer_safe else "infeasible",
        "auto_plan_72h_valid": execution_buffer_safe,
        "auto_plan_72h_reason": (
            "72-uurs planpreview berekend; veiligheidslading heeft voorrang, "
            "daarna solar, woningdekking en observerende handel"
            if execution_buffer_safe
            else "sequentiele safety-replay kan execution-reserve niet halen"
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
        "auto_plan_72h_execution_buffer_safe": execution_buffer_safe,
        "auto_plan_72h_first_execution_breach": first_execution_breach,
        "auto_plan_72h_safety_plan_authority": "doems_alpha38_split_reserve_safety_reachability_v1",
        "auto_plan_72h_upstream_safety_advice_only": True,
        "auto_plan_72h_upstream_safety_advice_stored_kwh": upstream_safety_advice_stored_kwh,
        "auto_plan_72h_safety_plan_replay_count": sequential_safety["replay_count"],
        "auto_plan_72h_safety_plan_requested_stored_kwh": sequential_safety["requested_stored_kwh"],
        "auto_plan_72h_safety_plan_accepted_stored_kwh": sequential_safety["accepted_stored_kwh"],
        "auto_plan_72h_safety_plan_accepted_grid_input_kwh": sequential_safety["accepted_grid_input_kwh"],
        "auto_plan_72h_safety_plan_unmet_deadlines": sequential_safety["breaches"],
        "auto_plan_72h_reserve_policy": "fixed_operational_reserve_v1",
        "auto_plan_72h_safety_reachability_policy": "split_reserve_safety_reachability_v1",
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
            "DOEMS Alpha38 Design C houdt de operationele reserve vast op de "
            "technische+software-reserve en gebruikt toekomstige woningbehoefte "
            "alleen voor safety-targets, precharge-reachability en fail-closed deadlines."
        ),
    }
