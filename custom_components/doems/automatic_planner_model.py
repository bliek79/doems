"""R5 shadow automatic planner on the native DOEMS quarter route."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any, Mapping, Sequence

from .manual_soc_projection_model import (
    FORECAST_SLOTS, SLOT_SECONDS, MIN_SOC_PERCENT, MAX_SOC_PERCENT,
    CHARGE_EFFICIENCY, DISCHARGE_EFFICIENCY, _manual_commitments,
    _slot_price, _validate_time_axis,
)

DEFAULT_SOFTWARE_RESERVE_PERCENT = 5.0
DEFAULT_MAX_CHARGE_POWER_W = 3500.0
DEFAULT_MAX_DISCHARGE_POWER_W = 3500.0
DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH = 0.10
DEFAULT_PEAK_SALE_THRESHOLD_EUR_PER_KWH = 0.50
_EPS = 0.0005


def _simulate(
    axis,
    commitments,
    start_soc,
    capacity,
    ce,
    de,
    max_c,
    max_d,
    safety=None,
    trade_c=None,
    trade_d=None,
    peak_d=None,
    reserve_floor_end_soc=None,
):
    safety, trade_c, trade_d, peak_d = (
        safety or {},
        trade_c or {},
        trade_d or {},
        peak_d or {},
    )
    floor_end = reserve_floor_end_soc or [MIN_SOC_PERCENT] * len(axis)
    soc = max(MIN_SOC_PERCENT, min(MAX_SOC_PERCENT, float(start_soc)))
    rows = []
    for slot in axis:
        i = slot["index"]
        start = slot["start"]
        end = slot["end"]
        automatic_floor = max(
            MIN_SOC_PERCENT,
            min(MAX_SOC_PERCENT, float(floor_end[i])),
        )
        active = []
        for plan in commitments:
            overlap = max(
                0.0,
                (min(end, plan["end"]) - max(start, plan["start"])).total_seconds(),
            )
            if overlap > 0:
                active.append((plan, overlap))

        manual_seconds = sum(value for _, value in active)
        auto_seconds = max(0.0, SLOT_SECONDS - manual_seconds)
        frac = auto_seconds / SLOT_SECONDS
        home = float(slot["home_kwh"]) * frac
        solar = float(slot["solar_kwh"]) * frac
        home_total = float(slot["home_kwh"])
        solar_total = float(slot["solar_kwh"])
        soc_start = soc

        solar_to_home = min(home, solar)
        surplus = max(0.0, solar - solar_to_home)
        deficit = max(0.0, home - solar_to_home)

        charge_limit = max_c / 1000.0 * auto_seconds / 3600.0
        discharge_limit = max_d / 1000.0 * auto_seconds / 3600.0
        charge_headroom = max(
            0.0,
            (MAX_SOC_PERCENT - soc) / 100.0 * capacity / ce,
        )
        solar_charge = min(surplus, charge_limit, charge_headroom)
        soc += solar_charge * ce / capacity * 100.0
        charge_left = charge_limit - solar_charge

        def charge(requested):
            nonlocal soc, charge_left
            headroom = max(
                0.0,
                (MAX_SOC_PERCENT - soc) / 100.0 * capacity / ce,
            )
            value = min(max(0.0, requested), charge_left, headroom)
            soc += value * ce / capacity * 100.0
            charge_left -= value
            return value

        safety_charge = charge(float(safety.get(i, 0.0)))
        trade_charge = charge(float(trade_c.get(i, 0.0)))

        available_output = max(
            0.0,
            (soc - automatic_floor) / 100.0 * capacity * de,
        )
        home_discharge = min(deficit, discharge_limit, available_output)
        soc -= home_discharge / de / capacity * 100.0
        discharge_left = discharge_limit - home_discharge

        def discharge(requested):
            nonlocal soc, discharge_left
            available = max(
                0.0,
                (soc - automatic_floor) / 100.0 * capacity * de,
            )
            value = min(max(0.0, requested), discharge_left, available)
            soc -= value / de / capacity * 100.0
            discharge_left -= value
            return value

        trade_discharge = discharge(float(trade_d.get(i, 0.0)))
        peak_discharge = discharge(float(peak_d.get(i, 0.0)))

        manual_charge = 0.0
        manual_discharge = 0.0
        manual_slots = []
        for plan, seconds in active:
            requested = (
                min(float(plan["power_w"]), 3500.0)
                / 1000.0
                * seconds
                / 3600.0
            )
            target = max(
                MIN_SOC_PERCENT,
                min(MAX_SOC_PERCENT, float(plan["target_soc"])),
            )
            if plan["action"] == "laden":
                need = max(
                    0.0,
                    (target - soc) / 100.0 * capacity / ce,
                )
                value = min(requested, need)
                soc += value * ce / capacity * 100.0
                manual_charge += value
            else:
                available = max(
                    0.0,
                    (soc - target) / 100.0 * capacity * de,
                )
                value = min(requested, available)
                soc -= value / de / capacity * 100.0
                manual_discharge += value
            manual_slots.append(int(plan["slot"]))

        soc = max(MIN_SOC_PERCENT, min(MAX_SOC_PERCENT, soc))
        prices = slot["prices"]
        actions = []
        if safety_charge > _EPS:
            actions.append("veiligheidsladen")
        if trade_charge > _EPS:
            actions.append("handelsladen")
        if trade_discharge > _EPS:
            actions.append("handel_ontladen")
        if peak_discharge > _EPS:
            actions.append("piek_ontladen")

        rows.append(
            {
                "index": i,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "home_kwh": round(home_total, 6),
                "home_consumption_kwh": round(home_total, 6),
                "solar_kwh": round(solar_total, 6),
                **prices,
                "start_soc_percent": round(soc_start, 6),
                "end_soc_percent": round(soc, 6),
                "soc_end": round(soc, 6),
                "solar_to_home_kwh": round(solar_to_home, 6),
                "charge_from_solar_kwh": round(solar_charge, 6),
                "charge_from_grid_safety_kwh": round(safety_charge, 6),
                "charge_from_grid_trade_kwh": round(trade_charge, 6),
                "charge_from_grid_kwh": round(safety_charge + trade_charge, 6),
                "discharge_to_home_kwh": round(home_discharge, 6),
                "trade_discharge_to_grid_kwh": round(trade_discharge, 6),
                "peak_sale_to_grid_kwh": round(peak_discharge, 6),
                "discharge_to_grid_kwh": round(
                    trade_discharge + peak_discharge,
                    6,
                ),
                "grid_to_home_kwh": round(
                    max(0.0, deficit - home_discharge),
                    6,
                ),
                "grid_import_for_home_kwh": round(
                    max(0.0, deficit - home_discharge),
                    6,
                ),
                "solar_to_grid_kwh": round(
                    max(0.0, surplus - solar_charge),
                    6,
                ),
                "solar_export_kwh": round(
                    max(0.0, surplus - solar_charge),
                    6,
                ),
                "manual_charge_kwh": round(manual_charge, 6),
                "manual_discharge_kwh": round(manual_discharge, 6),
                "manual_slots": sorted(set(manual_slots)),
                "automatic_action": (
                    "+".join(actions) if actions else "geen_actie"
                ),
                "automatic_candidate": bool(actions),
                "charge_headroom_kwh": round(
                    min(
                        charge_left,
                        max(
                            0.0,
                            (MAX_SOC_PERCENT - soc)
                            / 100.0
                            * capacity
                            / ce,
                        ),
                    ),
                    6,
                ),
                "discharge_headroom_kwh": round(
                    min(
                        discharge_left,
                        max(
                            0.0,
                            (soc - automatic_floor)
                            / 100.0
                            * capacity
                            * de,
                        ),
                    ),
                    6,
                ),
                "automatic_floor_soc_percent": round(automatic_floor, 6),
                "observational_only": True,
            }
        )
    return rows


def _full_clock_hour_buckets(axis):
    groups = defaultdict(list)
    for slot in axis:
        start = slot["start"]
        bucket = start.replace(minute=0, second=0, microsecond=0)
        groups[bucket].append(slot)

    buckets = []
    for bucket_start in sorted(groups):
        rows = sorted(groups[bucket_start], key=lambda item: item["start"])
        if len(rows) != 4:
            continue
        if [row["start"].minute for row in rows] != [0, 15, 30, 45]:
            continue
        if rows[0]["start"] != bucket_start:
            continue
        if rows[-1]["end"] != bucket_start + timedelta(hours=1):
            continue
        home = sum(float(row["home_kwh"]) for row in rows)
        solar = sum(float(row["solar_kwh"]) for row in rows)
        buckets.append(
            {
                "start": bucket_start,
                "end": bucket_start + timedelta(hours=1),
                "first_index": int(rows[0]["index"]),
                "last_index": int(rows[-1]["index"]),
                "home_kwh": home,
                "solar_kwh": solar,
                "usable": solar > 0.0 and solar >= home,
            }
        )
    return buckets


def _usable_solar_pairs(axis):
    buckets = _full_clock_hour_buckets(axis)
    pairs = []
    for first, second in zip(buckets, buckets[1:]):
        if first["end"] != second["start"]:
            continue
        if not first["usable"] or not second["usable"]:
            continue
        pairs.append(
            {
                "start": first["start"],
                "first_index": first["first_index"],
                "first_last_index": first["last_index"],
                "second_last_index": second["last_index"],
            }
        )
    return pairs


def _next_usable_solar_index(pairs, start_index):
    for pair in pairs:
        if pair["first_last_index"] < start_index:
            continue
        if pair["first_index"] <= start_index <= pair["first_last_index"]:
            return start_index
        return pair["first_index"]
    return None


def _dynamic_reserve_profile(axis, capacity, base_floor_soc, discharge_efficiency):
    pairs = _usable_solar_pairs(axis)
    deficits = [
        max(0.0, float(slot["home_kwh"]) - float(slot["solar_kwh"]))
        for slot in axis
    ]
    prefix = [0.0]
    for value in deficits:
        prefix.append(prefix[-1] + value)

    base_floor_kwh = capacity * base_floor_soc / 100.0
    profile = []
    for index in range(len(axis) + 1):
        matching = None
        for pair in pairs:
            if pair["first_last_index"] >= index:
                matching = pair
                break

        if matching is None:
            need_home_kwh = 0.0
            next_usable = None
            complete = False
        else:
            next_usable = matching["start"].isoformat()
            complete = True
            if matching["first_index"] <= index <= matching["first_last_index"]:
                need_home_kwh = 0.0
            else:
                stop = matching["first_index"]
                need_home_kwh = max(0.0, prefix[stop] - prefix[index])

        stored_need_kwh = need_home_kwh / discharge_efficiency
        floor_kwh = min(
            capacity,
            max(base_floor_kwh, base_floor_kwh + stored_need_kwh),
        )
        profile.append(
            {
                "floor_kwh": floor_kwh,
                "floor_soc": floor_kwh / capacity * 100.0,
                "need_home_kwh": need_home_kwh,
                "next_usable_solar": next_usable,
                "solar_horizon_complete": complete,
            }
        )
    return profile, pairs


def _hours(rows):
    groups = defaultdict(list)
    from datetime import datetime

    for row in rows:
        start = datetime.fromisoformat(row["start"])
        groups[start.replace(minute=0, second=0, microsecond=0)].append(row)

    sums = (
        "solar_kwh",
        "home_consumption_kwh",
        "solar_to_home_kwh",
        "charge_from_solar_kwh",
        "charge_from_grid_safety_kwh",
        "charge_from_grid_trade_kwh",
        "charge_from_grid_kwh",
        "discharge_to_home_kwh",
        "discharge_to_grid_kwh",
        "trade_discharge_to_grid_kwh",
        "peak_sale_to_grid_kwh",
        "grid_import_for_home_kwh",
        "solar_export_kwh",
        "manual_charge_kwh",
        "manual_discharge_kwh",
    )
    out = []
    for start in sorted(groups):
        rows_in_hour = groups[start]
        item = {
            "time": start.isoformat(),
            "slot_count": len(rows_in_hour),
            "soc_start": rows_in_hour[0]["start_soc_percent"],
            "soc_end": rows_in_hour[-1]["end_soc_percent"],
            "manual_slots": sorted(
                {
                    slot
                    for row in rows_in_hour
                    for slot in row["manual_slots"]
                }
            ),
            "replanned": True,
            "automatic_planner_shadow": True,
        }
        for key in sums:
            item[key] = round(
                sum(float(row.get(key) or 0.0) for row in rows_in_hour),
                6,
            )
        import_prices = [
            row["import_price"]
            for row in rows_in_hour
            if row.get("import_price") is not None
        ]
        export_prices = [
            row["export_price"]
            for row in rows_in_hour
            if row.get("export_price") is not None
        ]
        if import_prices:
            item["price"] = item["import_price"] = round(
                sum(import_prices) / len(import_prices),
                8,
            )
        if export_prices:
            item["export_price"] = round(
                sum(export_prices) / len(export_prices),
                8,
            )
        out.append(item)
    return out


def build_automatic_plan(
    *,
    energy_slots: Sequence[Mapping[str, Any]],
    solar_slots: Sequence[Mapping[str, Any]],
    plans: Sequence[Mapping[str, Any]],
    start_soc_percent: float,
    capacity_kwh: float,
    price_by_start: Mapping[str, Mapping[str, Any]] | None,
    software_reserve_percent: float = DEFAULT_SOFTWARE_RESERVE_PERCENT,
    charge_efficiency: float = CHARGE_EFFICIENCY,
    discharge_efficiency: float = DISCHARGE_EFFICIENCY,
    max_charge_power_w: float = DEFAULT_MAX_CHARGE_POWER_W,
    max_discharge_power_w: float = DEFAULT_MAX_DISCHARGE_POWER_W,
    minimum_trade_margin_eur_per_kwh: float = (
        DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH
    ),
    peak_sale_threshold_eur_per_kwh: float = (
        DEFAULT_PEAK_SALE_THRESHOLD_EUR_PER_KWH
    ),
) -> dict[str, Any]:
    blockers = []
    try:
        soc = float(start_soc_percent)
        capacity = float(capacity_kwh)
        reserve = float(software_reserve_percent)
        charge_eff = float(charge_efficiency)
        discharge_eff = float(discharge_efficiency)
        max_charge = float(max_charge_power_w)
        max_discharge = float(max_discharge_power_w)
        margin = float(minimum_trade_margin_eur_per_kwh)
        peak_threshold = float(peak_sale_threshold_eur_per_kwh)
    except (TypeError, ValueError):
        return {
            "status": "blocked",
            "valid": False,
            "blockers": ["planner_setting_invalid"],
            "physical_execution_authority": False,
        }

    if not 0.0 <= soc <= 100.0:
        blockers.append("start_soc_invalid")
    if capacity <= 0.0:
        blockers.append("capacity_invalid")
    if not 0.0 <= reserve <= 30.0 or MIN_SOC_PERCENT + reserve > 100.0:
        blockers.append("software_reserve_invalid")
    if not 0.5 <= charge_eff <= 1.0:
        blockers.append("charge_efficiency_invalid")
    if not 0.5 <= discharge_eff <= 1.0:
        blockers.append("discharge_efficiency_invalid")
    if not 100.0 <= max_charge <= 3500.0:
        blockers.append("max_charge_power_invalid")
    if not 100.0 <= max_discharge <= 3500.0:
        blockers.append("max_discharge_power_invalid")
    if margin < 0.0:
        blockers.append("trade_margin_invalid")
    if peak_threshold < 0.0:
        blockers.append("peak_sale_threshold_invalid")

    axis0, axis_blockers = _validate_time_axis(energy_slots, solar_slots)
    blockers += axis_blockers
    commitments, commitment_blockers = _manual_commitments(plans)
    blockers += commitment_blockers

    axis = []
    for row in axis0:
        prices = _slot_price(price_by_start, row["start"])
        if prices["import_price"] is None or prices["export_price"] is None:
            blockers.append(f"price_slot_{row['index']}_missing")
        axis.append({**row, "prices": prices})

    base_floor = MIN_SOC_PERCENT + reserve
    base = {
        "automatic_planner_active": True,
        "automatic_plan_store_writes": False,
        "scheduler_active": False,
        "safety_prestart_active": False,
        "execution_enabled": False,
        "physical_execution_authority": False,
        "mode": "automatic_planner_shadow",
        "observational_only": True,
    }
    if blockers:
        return {
            "status": "blocked",
            "valid": False,
            "blockers": sorted(set(blockers)),
            "native_slots": [],
            "hourly_plan": [],
            "candidates": [],
            **base,
        }

    reserve_profile, usable_pairs = _dynamic_reserve_profile(
        axis,
        capacity,
        base_floor,
        discharge_eff,
    )
    reserve_floor_end = [
        reserve_profile[index + 1]["floor_soc"]
        for index in range(len(axis))
    ]

    safety = {}
    trade_charge = {}
    trade_discharge = {}
    peak_discharge = {}
    roundtrip = charge_eff * discharge_eff

    def simulate():
        return _simulate(
            axis,
            commitments,
            soc,
            capacity,
            charge_eff,
            discharge_eff,
            max_charge,
            max_discharge,
            safety,
            trade_charge,
            trade_discharge,
            peak_discharge,
            reserve_floor_end,
        )

    initial = simulate()
    safety_needed = any(
        float(row["end_soc_percent"])
        < float(reserve_floor_end[index]) - 1e-6
        for index, row in enumerate(initial)
    )

    def fill_safety():
        for _ in range(FORECAST_SLOTS):
            route = simulate()
            breach = next(
                (
                    index
                    for index, row in enumerate(route)
                    if float(row["end_soc_percent"])
                    < float(reserve_floor_end[index]) - 1e-6
                ),
                None,
            )
            if breach is None:
                return

            required = float(reserve_floor_end[breach])
            need = required - float(route[breach]["end_soc_percent"])
            candidates = [
                index
                for index, row in enumerate(route[: breach + 1])
                if not row["manual_slots"]
                and row["import_price"] is not None
                and float(row["charge_headroom_kwh"]) > _EPS
                and peak_discharge.get(index, 0.0) <= _EPS
                and trade_charge.get(index, 0.0) <= _EPS
                and trade_discharge.get(index, 0.0) <= _EPS
            ]
            candidates.sort(
                key=lambda index: (
                    route[index]["import_price"],
                    -index,
                )
            )

            made = False
            for index in candidates:
                max_input = float(route[index]["charge_headroom_kwh"])
                old = safety.get(index, 0.0)
                safety[index] = old + max_input
                trial = simulate()
                gain = (
                    float(trial[breach]["end_soc_percent"])
                    - float(route[breach]["end_soc_percent"])
                )
                safety[index] = old
                if gain <= 1e-6:
                    continue
                add = (
                    max_input
                    if gain <= need
                    else max_input * need / gain
                )
                safety[index] = old + add
                made = True
                break
            if not made:
                return

    fill_safety()

    route = simulate()
    for index in sorted(
        [
            index
            for index, row in enumerate(route)
            if not row["manual_slots"]
            and row["export_price"] is not None
            and float(row["export_price"]) >= peak_threshold
            and safety.get(index, 0.0) <= _EPS
            and trade_charge.get(index, 0.0) <= _EPS
            and trade_discharge.get(index, 0.0) <= _EPS
        ],
        key=lambda index: (
            -float(route[index]["export_price"]),
            index,
        ),
    ):
        route = simulate()
        export_price = float(route[index]["export_price"])
        pv_reload = _next_usable_solar_index(usable_pairs, index + 1)
        grid_reload = next(
            (
                future
                for future in range(index + 1, len(axis))
                if axis[future]["prices"]["import_price"] is not None
                and not route[future]["manual_slots"]
                and export_price
                - float(axis[future]["prices"]["import_price"]) / roundtrip
                >= margin
            ),
            None,
        )
        options = [
            candidate
            for candidate in (pv_reload, grid_reload)
            if candidate is not None
        ]
        if not options:
            continue
        reload_index = min(options)
        interval = route[index:reload_index]
        if not interval:
            continue

        slack_output = min(
            max(
                0.0,
                (
                    float(row["end_soc_percent"])
                    - float(reserve_floor_end[row["index"]])
                )
                / 100.0
                * capacity
                * discharge_eff,
            )
            for row in interval
        )
        add = min(
            slack_output,
            float(route[index]["discharge_headroom_kwh"]),
        )
        if add > _EPS:
            peak_discharge[index] = add

    route = simulate()
    usable_from_start = _next_usable_solar_index(usable_pairs, 0)
    best = None
    for charge_index, charge_row in enumerate(route[:-1]):
        if charge_row["manual_slots"]:
            continue
        if safety.get(charge_index, 0.0) > _EPS:
            continue
        if peak_discharge.get(charge_index, 0.0) > _EPS:
            continue
        if charge_row["import_price"] is None:
            continue
        if float(charge_row["charge_headroom_kwh"]) <= _EPS:
            continue
        if (
            usable_from_start is not None
            and charge_index < usable_from_start
        ):
            continue

        cycle_cost = float(charge_row["import_price"]) / roundtrip
        for discharge_index in range(charge_index + 1, len(route)):
            discharge_row = route[discharge_index]
            if discharge_row["manual_slots"]:
                continue
            if safety.get(discharge_index, 0.0) > _EPS:
                continue
            if peak_discharge.get(discharge_index, 0.0) > _EPS:
                continue
            if discharge_row["export_price"] is None:
                continue

            trade_margin = float(discharge_row["export_price"]) - cycle_cost
            if trade_margin >= margin and (
                best is None or trade_margin > best[0]
            ):
                best = (
                    trade_margin,
                    charge_index,
                    discharge_index,
                )

    if best:
        _, charge_index, discharge_index = best
        route = simulate()
        charge_input = float(route[charge_index]["charge_headroom_kwh"])
        if charge_input > _EPS:
            trade_charge[charge_index] = charge_input
            charged = simulate()
            slack_values = []
            for row in charged[discharge_index:]:
                floor_soc = float(reserve_floor_end[row["index"]])
                slack_values.append(
                    max(
                        0.0,
                        (
                            float(row["end_soc_percent"]) - floor_soc
                        )
                        / 100.0
                        * capacity
                        * discharge_eff,
                    )
                )
            free_output = min(slack_values) if slack_values else 0.0
            discharge_output = min(
                free_output,
                float(charged[discharge_index]["discharge_headroom_kwh"]),
                charge_input * roundtrip,
            )
            if discharge_output > _EPS:
                trade_charge[charge_index] = (
                    discharge_output / roundtrip
                )
                trade_discharge[discharge_index] = discharge_output
            else:
                trade_charge.pop(charge_index, None)

    final = simulate()
    candidates = []
    candidate_fields = (
        (
            "charge_from_grid_safety_kwh",
            "veiligheidsladen",
            "laden",
            "dynamic_reserve_protection",
        ),
        (
            "charge_from_grid_trade_kwh",
            "handelsladen",
            "laden",
            "normal_arbitrage_margin",
        ),
        (
            "trade_discharge_to_grid_kwh",
            "handel_ontladen",
            "ontladen",
            "normal_arbitrage_margin",
        ),
        (
            "peak_sale_to_grid_kwh",
            "piek_ontladen",
            "ontladen",
            "peak_price_with_protected_route_to_recharge",
        ),
    )
    for row in final:
        index = int(row["index"])
        start_reserve = reserve_profile[index]
        end_reserve = reserve_profile[index + 1]
        row.update(
            {
                "dynamic_reserve_floor_start_soc_percent": round(
                    float(start_reserve["floor_soc"]),
                    6,
                ),
                "dynamic_reserve_floor_end_soc_percent": round(
                    float(end_reserve["floor_soc"]),
                    6,
                ),
                "dynamic_reserve_floor_start_kwh": round(
                    float(start_reserve["floor_kwh"]),
                    6,
                ),
                "dynamic_reserve_floor_end_kwh": round(
                    float(end_reserve["floor_kwh"]),
                    6,
                ),
                "dynamic_need_until_usable_solar_kwh": round(
                    float(start_reserve["need_home_kwh"]),
                    6,
                ),
                "next_usable_solar": start_reserve["next_usable_solar"],
                "solar_horizon_complete": bool(
                    start_reserve["solar_horizon_complete"]
                ),
            }
        )
        for field, candidate_type, action, reason in candidate_fields:
            energy = float(row.get(field) or 0.0)
            if energy > _EPS:
                candidates.append(
                    {
                        "type": candidate_type,
                        "action": action,
                        "time": row["start"],
                        "energy_kwh": round(energy, 6),
                        "power_w": round(energy * 4000.0, 1),
                        "import_price": row.get("import_price"),
                        "export_price": row.get("export_price"),
                        "reason": reason,
                    }
                )

    candidates.sort(key=lambda item: (item["time"], item["type"]))
    soc_values = [float(row["end_soc_percent"]) for row in final]
    next_candidate = candidates[0] if candidates else None
    hourly = _hours(final)

    safety_sufficient = all(
        float(row["end_soc_percent"])
        >= float(reserve_floor_end[index]) - 1e-6
        for index, row in enumerate(final)
    )
    reserve_values = [
        float(item["floor_soc"])
        for item in reserve_profile[:-1]
    ]
    start_reserve = reserve_profile[0]
    incomplete_slots = sum(
        1
        for item in reserve_profile[:-1]
        if not item["solar_horizon_complete"]
    )

    return {
        "status": "ready",
        "valid": True,
        "blockers": [],
        "decision": (
            next_candidate["type"] if next_candidate else "geen_actie"
        ),
        "reason": (
            next_candidate["reason"]
            if next_candidate
            else "no_automatic_candidate"
        ),
        "next_candidate": next_candidate,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "candidate_types": sorted(
            {item["type"] for item in candidates}
        ),
        "native_slots": final,
        "hourly_plan": hourly,
        "native_slot_count": len(final),
        "clock_hour_bucket_count": len(hourly),
        "start": final[0]["start"],
        "end": final[-1]["end"],
        "start_soc_percent": soc,
        "end_soc_percent": final[-1]["end_soc_percent"],
        "projected_min_soc_percent": round(min(soc_values), 6),
        "projected_max_soc_percent": round(max(soc_values), 6),
        "technical_min_soc_percent": MIN_SOC_PERCENT,
        "software_reserve_percent": reserve,
        "planner_floor_soc_percent": base_floor,
        "planner_floor_kwh": round(
            capacity * base_floor / 100.0,
            6,
        ),
        "dynamic_reserve_start_soc_percent": round(
            float(start_reserve["floor_soc"]),
            6,
        ),
        "dynamic_reserve_min_soc_percent": round(
            min(reserve_values),
            6,
        ),
        "dynamic_reserve_max_soc_percent": round(
            max(reserve_values),
            6,
        ),
        "dynamic_need_until_usable_solar_kwh": round(
            float(start_reserve["need_home_kwh"]),
            6,
        ),
        "next_usable_solar": start_reserve["next_usable_solar"],
        "solar_horizon_complete": bool(
            start_reserve["solar_horizon_complete"]
        ),
        "solar_horizon_incomplete_slots": incomplete_slots,
        "capacity_kwh": round(capacity, 6),
        "capacity_source": "battery_input_contract_live_sensor",
        "charge_efficiency_percent": round(charge_eff * 100.0, 1),
        "discharge_efficiency_percent": round(
            discharge_eff * 100.0,
            1,
        ),
        "roundtrip_efficiency_percent": round(roundtrip * 100.0, 2),
        "max_charge_power_w": max_charge,
        "max_discharge_power_w": max_discharge,
        "minimum_trade_margin_eur_per_kwh": margin,
        "peak_sale_threshold_eur_per_kwh": peak_threshold,
        "safety_charge_needed": safety_needed,
        "safety_schedule_sufficient": safety_sufficient,
        "safety_charge_kwh": round(sum(safety.values()), 6),
        "trade_charge_kwh": round(sum(trade_charge.values()), 6),
        "trade_discharge_kwh": round(
            sum(trade_discharge.values()),
            6,
        ),
        "peak_sale_kwh": round(sum(peak_discharge.values()), 6),
        "manual_commitment_count": len(commitments),
        "manual_commitment_slots": [
            plan["slot"] for plan in commitments
        ],
        "usable_solar_rule": (
            "first_of_two_consecutive_full_clock_hours_"
            "where_total_solar_gte_total_home"
        ),
        "dynamic_reserve_rule": (
            "base_floor_plus_home_deficit_until_next_usable_solar_"
            "with_incomplete_horizon_fallback_to_base_floor"
        ),
        **base,
    }
