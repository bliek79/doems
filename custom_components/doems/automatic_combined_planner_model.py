"""Automatic and Combined Planner models on the native DOEMS route.

The Automatic Planner calculates the autonomous 288-slot route. The Combined
Planner applies existing manual commitments as hard constraints and replans the
remaining route. This module never writes plans and never controls hardware.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from collections.abc import Callable
from typing import Any, Mapping, Sequence

from .planner_diagnostics import PlannerDiagnostics

from .manual_soc_projection_model import (
    CHARGE_EFFICIENCY,
    DISCHARGE_EFFICIENCY,
    FORECAST_SLOTS,
    MAX_SOC_PERCENT,
    MIN_SOC_PERCENT,
    SLOT_SECONDS,
    _manual_commitments,
    _slot_price,
    _validate_time_axis,
)

DEFAULT_SOFTWARE_RESERVE_PERCENT = 5.0
DEFAULT_MAX_CHARGE_POWER_W = 3500.0
DEFAULT_MAX_DISCHARGE_POWER_W = 3500.0
DEFAULT_MINIMUM_TRADE_MARGIN_EUR_PER_KWH = 0.10
_EPS = 0.0005


class PlannerComputeCancelled(RuntimeError):
    """An obsolete planner generation was cooperatively interrupted."""


class PlannerComputeBudgetExceeded(RuntimeError):
    """The planner did not finish inside its bounded worker time."""

USABLE_SOLAR_RULE = (
    "first_of_two_consecutive_full_clock_hours_"
    "where_total_solar_gte_total_home"
)
DYNAMIC_RESERVE_RULE = "fixed_hard_safety_floor_with_separate_planning_need"


def _full_clock_hour_buckets(axis: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate complete native quarters only for the usable-solar decision."""
    groups: dict[datetime, list[Mapping[str, Any]]] = defaultdict(list)
    for slot in axis:
        start = slot["start"]
        bucket = start.replace(minute=0, second=0, microsecond=0)
        groups[bucket].append(slot)

    buckets: list[dict[str, Any]] = []
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


def _usable_solar_pairs(axis: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return consecutive full clock-hour pairs that both cover home demand."""
    buckets = _full_clock_hour_buckets(axis)
    pairs: list[dict[str, Any]] = []
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


def _next_usable_solar_index(
    pairs: Sequence[Mapping[str, Any]], start_index: int
) -> int | None:
    for pair in pairs:
        if int(pair["first_last_index"]) < start_index:
            continue
        if int(pair["first_index"]) <= start_index <= int(pair["first_last_index"]):
            return start_index
        return int(pair["first_index"])
    return None


def _dynamic_reserve_profile(
    axis: Sequence[Mapping[str, Any]],
    capacity_kwh: float,
    base_floor_soc: float,
    discharge_efficiency: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Report planning need to usable solar without increasing the hard SOC floor."""
    pairs = _usable_solar_pairs(axis)
    deficits = [
        max(0.0, float(slot["home_kwh"]) - float(slot["solar_kwh"]))
        for slot in axis
    ]
    prefix = [0.0]
    for value in deficits:
        prefix.append(prefix[-1] + value)

    base_floor_kwh = capacity_kwh * base_floor_soc / 100.0
    profile: list[dict[str, Any]] = []
    for index in range(len(axis) + 1):
        matching = next(
            (
                pair
                for pair in pairs
                if int(pair["first_last_index"]) >= index
            ),
            None,
        )
        if matching is None:
            # Proven Alpha24.4 fallback: an unknown/no-later solar block must
            # not turn the complete remainder of the 72-hour forecast into a
            # protected reserve.
            need_home_kwh = 0.0
            next_usable = None
            complete = False
        else:
            next_usable = matching["start"].isoformat()
            complete = True
            first_index = int(matching["first_index"])
            first_last_index = int(matching["first_last_index"])
            if first_index <= index <= first_last_index:
                need_home_kwh = 0.0
            else:
                need_home_kwh = max(0.0, prefix[first_index] - prefix[index])

        stored_need_kwh = need_home_kwh / discharge_efficiency
        # Forecast demand is planning information, never a hard reserve.
        floor_kwh = base_floor_kwh
        profile.append(
            {
                "floor_kwh": floor_kwh,
                "floor_soc": floor_kwh / capacity_kwh * 100.0,
                "need_home_kwh": need_home_kwh,
                "next_usable_solar": next_usable,
                "solar_horizon_complete": complete,
            }
        )
    return profile, pairs


def _simulate(
    *,
    axis: Sequence[Mapping[str, Any]],
    commitments: Sequence[Mapping[str, Any]],
    start_soc_percent: float,
    capacity_kwh: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    max_charge_power_w: float,
    max_discharge_power_w: float,
    reserve_floor_end_soc: Sequence[float],
    safety: Mapping[int, float] | None = None,
    trade_charge: Mapping[int, float] | None = None,
    trade_discharge: Mapping[int, float] | None = None,
    check_work: Callable[[], None] | None = None,
    compact: bool = False,
) -> list[dict[str, Any]]:
    """Simulate one native route with manual commitments taking hard priority.

    Trial routes contain only fields needed for optimization; public output
    retains the complete established native-slot contract.
    """
    safety = safety or {}
    trade_charge = trade_charge or {}
    trade_discharge = trade_discharge or {}
    soc = max(MIN_SOC_PERCENT, min(MAX_SOC_PERCENT, float(start_soc_percent)))
    rows: list[dict[str, Any]] = []

    for slot in axis:
        index = int(slot["index"])
        if check_work is not None and index % 16 == 0:
            check_work()
        start = slot["start"]
        end = slot["end"]
        automatic_floor = max(
            MIN_SOC_PERCENT,
            min(MAX_SOC_PERCENT, float(reserve_floor_end_soc[index])),
        )

        active: list[tuple[Mapping[str, Any], float]] = []
        for plan in commitments:
            overlap = max(
                0.0,
                (
                    min(end, plan["end"]) - max(start, plan["start"])
                ).total_seconds(),
            )
            if overlap > 0.0:
                active.append((plan, overlap))

        manual_seconds = sum(seconds for _, seconds in active)
        automatic_seconds = max(0.0, SLOT_SECONDS - manual_seconds)
        automatic_fraction = automatic_seconds / SLOT_SECONDS
        home_total = float(slot["home_kwh"])
        solar_total = float(slot["solar_kwh"])
        home = home_total * automatic_fraction
        solar = solar_total * automatic_fraction
        soc_start = soc

        solar_to_home = min(home, solar)
        surplus = max(0.0, solar - solar_to_home)
        deficit = max(0.0, home - solar_to_home)

        charge_limit = (
            max_charge_power_w / 1000.0 * automatic_seconds / 3600.0
        )
        discharge_limit = (
            max_discharge_power_w / 1000.0 * automatic_seconds / 3600.0
        )
        charge_headroom = max(
            0.0,
            (MAX_SOC_PERCENT - soc)
            / 100.0
            * capacity_kwh
            / charge_efficiency,
        )
        solar_charge = min(surplus, charge_limit, charge_headroom)
        soc += solar_charge * charge_efficiency / capacity_kwh * 100.0
        charge_left = charge_limit - solar_charge

        def charge(requested_kwh: float) -> float:
            nonlocal soc, charge_left
            headroom = max(
                0.0,
                (MAX_SOC_PERCENT - soc)
                / 100.0
                * capacity_kwh
                / charge_efficiency,
            )
            actual = min(max(0.0, requested_kwh), charge_left, headroom)
            soc += actual * charge_efficiency / capacity_kwh * 100.0
            charge_left -= actual
            return actual

        safety_charge = charge(float(safety.get(index, 0.0)))
        arbitrage_charge = charge(float(trade_charge.get(index, 0.0)))
        # Available automatic grid-charge room must be measured at the actual
        # charging step, before household discharge and manual commitments.
        # Using end-of-slot SOC invents headroom when the battery was full
        # during the charge phase, causing futile expensive safety trials.
        remaining_grid_charge_headroom = min(
            charge_left,
            max(
                0.0,
                (MAX_SOC_PERCENT - soc)
                / 100.0
                * capacity_kwh
                / charge_efficiency,
            ),
        )

        # Normal household self-consumption is physical discharge down to
        # the *technical* device minimum. The higher software planning target
        # is an economic precharge deadline, never a fictitious home hold.
        # The already computed automatic_floor remains the protected floor
        # for optional export/trade discharge.
        available_output = max(
            0.0,
            (soc - MIN_SOC_PERCENT)
            / 100.0
            * capacity_kwh
            * discharge_efficiency,
        )
        home_discharge = min(deficit, discharge_limit, available_output)
        soc -= (
            home_discharge
            / discharge_efficiency
            / capacity_kwh
            * 100.0
        )
        discharge_left = discharge_limit - home_discharge

        def discharge(requested_kwh: float) -> float:
            nonlocal soc, discharge_left
            available = max(
                0.0,
                (soc - automatic_floor)
                / 100.0
                * capacity_kwh
                * discharge_efficiency,
            )
            actual = min(max(0.0, requested_kwh), discharge_left, available)
            soc -= actual / discharge_efficiency / capacity_kwh * 100.0
            discharge_left -= actual
            return actual

        arbitrage_discharge = discharge(float(trade_discharge.get(index, 0.0)))

        manual_charge = 0.0
        manual_discharge = 0.0
        manual_slots: list[int] = []
        for plan, overlap_seconds in active:
            requested = (
                min(float(plan["power_w"]), 3500.0)
                / 1000.0
                * overlap_seconds
                / 3600.0
            )
            target = max(
                MIN_SOC_PERCENT,
                min(MAX_SOC_PERCENT, float(plan["target_soc"])),
            )
            if plan["action"] == "laden":
                need = max(
                    0.0,
                    (target - soc)
                    / 100.0
                    * capacity_kwh
                    / charge_efficiency,
                )
                actual = min(requested, need)
                soc += actual * charge_efficiency / capacity_kwh * 100.0
                manual_charge += actual
            else:
                available = max(
                    0.0,
                    (soc - target)
                    / 100.0
                    * capacity_kwh
                    * discharge_efficiency,
                )
                actual = min(requested, available)
                soc -= actual / discharge_efficiency / capacity_kwh * 100.0
                manual_discharge += actual
            manual_slots.append(int(plan["slot"]))

        soc = max(MIN_SOC_PERCENT, min(MAX_SOC_PERCENT, soc))
        prices = slot["prices"]
        if compact:
            # Repeated economic/safety candidate trials do not need 30+
            # descriptive public fields, timestamps, labels and rounding.
            # Preserve exactly the numeric precision used by the full route.
            rows.append(
                {
                    "index": index,
                    "end_soc_percent": round(soc, 6),
                    "manual_slots": sorted(set(manual_slots)),
                    "charge_headroom_kwh": round(
                        remaining_grid_charge_headroom, 6
                    ),
                    "discharge_headroom_kwh": round(
                        min(
                            discharge_left,
                            max(
                                0.0,
                                (soc - automatic_floor)
                                / 100.0
                                * capacity_kwh
                                * discharge_efficiency,
                            ),
                        ),
                        6,
                    ),
                    "grid_to_home_kwh": round(
                        max(0.0, deficit - home_discharge), 6
                    ),
                    "charge_from_grid_kwh": round(
                        safety_charge + arbitrage_charge, 6
                    ),
                    "solar_export_kwh": round(
                        max(0.0, surplus - solar_charge), 6
                    ),
                    "import_price": prices.get("import_price"),
                    "export_price": prices.get("export_price"),
                }
            )
            continue
        actions: list[str] = []
        if safety_charge > _EPS:
            actions.append("veiligheidsladen")
        if arbitrage_charge > _EPS:
            actions.append("handelsladen")
        if arbitrage_discharge > _EPS:
            actions.append("handel_ontladen")

        rows.append(
            {
                "index": index,
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
                "charge_from_grid_trade_kwh": round(arbitrage_charge, 6),
                "charge_from_grid_kwh": round(
                    safety_charge + arbitrage_charge, 6
                ),
                "discharge_to_home_kwh": round(home_discharge, 6),
                "trade_discharge_to_grid_kwh": round(
                    arbitrage_discharge, 6
                ),
                "discharge_to_grid_kwh": round(
                    arbitrage_discharge, 6
                ),
                "grid_to_home_kwh": round(
                    max(0.0, deficit - home_discharge), 6
                ),
                "grid_import_for_home_kwh": round(
                    max(0.0, deficit - home_discharge), 6
                ),
                "solar_to_grid_kwh": round(
                    max(0.0, surplus - solar_charge), 6
                ),
                "solar_export_kwh": round(
                    max(0.0, surplus - solar_charge), 6
                ),
                "manual_charge_kwh": round(manual_charge, 6),
                "manual_discharge_kwh": round(manual_discharge, 6),
                "manual_slots": sorted(set(manual_slots)),
                "manual_overlap_seconds": round(manual_seconds, 3),
                "automatic_fraction": round(automatic_fraction, 6),
                "automatic_action": (
                    "+".join(actions) if actions else "geen_actie"
                ),
                "automatic_candidate": bool(actions),
                "automatic_floor_soc_percent": round(
                    automatic_floor, 6
                ),
                "charge_headroom_kwh": round(
                    remaining_grid_charge_headroom, 6
                ),
                "discharge_headroom_kwh": round(
                    min(
                        discharge_left,
                        max(
                            0.0,
                            (soc - automatic_floor)
                            / 100.0
                            * capacity_kwh
                            * discharge_efficiency,
                        ),
                    ),
                    6,
                ),
            }
        )
    return rows


def _aggregate_clock_hours(
    native_slots: Sequence[Mapping[str, Any]],
    *,
    combined: bool,
) -> list[dict[str, Any]]:
    groups: dict[datetime, list[Mapping[str, Any]]] = defaultdict(list)
    for slot in native_slots:
        start = datetime.fromisoformat(str(slot["start"]))
        groups[start.replace(minute=0, second=0, microsecond=0)].append(slot)

    sums = (
        "solar_kwh",
        "home_consumption_kwh",
        "solar_to_home_kwh",
        "charge_from_solar_kwh",
        "charge_from_grid_safety_kwh",
        "charge_from_grid_trade_kwh",
        "charge_from_grid_kwh",
        "discharge_to_home_kwh",
        "trade_discharge_to_grid_kwh",
        "discharge_to_grid_kwh",
        "grid_import_for_home_kwh",
        "solar_export_kwh",
        "manual_charge_kwh",
        "manual_discharge_kwh",
    )
    result: list[dict[str, Any]] = []
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
            "planner_type": "combined" if combined else "automatic",
        }
        for field in sums:
            item[field] = round(
                sum(float(row.get(field) or 0.0) for row in rows), 6
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
        sources = [
            str(row["price_source"])
            for row in rows
            if row.get("price_source")
        ]
        kinds = [
            str(row["price_kind"])
            for row in rows
            if row.get("price_kind")
        ]
        if import_values:
            item["price"] = round(
                sum(import_values) / len(import_values), 8
            )
            item["import_price"] = item["price"]
        if export_values:
            item["export_price"] = round(
                sum(export_values) / len(export_values), 8
            )
        if sources:
            item["price_source"] = (
                "known" if all(value == "known" for value in sources)
                else "forecast"
            )
        if kinds:
            item["price_kind"] = (
                kinds[0] if all(value == kinds[0] for value in kinds)
                else "mixed"
            )
        if rows[0].get("dynamic_reserve_floor_start_soc_percent") is not None:
            item["dynamic_reserve_floor_start_soc_percent"] = rows[0].get(
                "dynamic_reserve_floor_start_soc_percent"
            )
        if rows[-1].get("dynamic_reserve_floor_end_soc_percent") is not None:
            item["dynamic_reserve_floor_end_soc_percent"] = rows[-1].get(
                "dynamic_reserve_floor_end_soc_percent"
            )
        result.append(item)
    return result


def _build_planner(
    *,
    axis: Sequence[Mapping[str, Any]],
    commitments: Sequence[Mapping[str, Any]],
    start_soc_percent: float,
    capacity_kwh: float,
    software_reserve_percent: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    max_charge_power_w: float,
    max_discharge_power_w: float,
    minimum_trade_margin_eur_per_kwh: float,
    combined: bool,
    check_work: Callable[[], None] | None = None,
    diagnostics: PlannerDiagnostics | None = None,
) -> dict[str, Any]:
    if diagnostics is not None:
        diagnostics.enter("model_setup")
    base_floor = MIN_SOC_PERCENT + software_reserve_percent
    reserve_profile, usable_pairs = _dynamic_reserve_profile(
        axis,
        capacity_kwh,
        base_floor,
        discharge_efficiency,
    )
    reserve_floor_end = [
        float(reserve_profile[index + 1]["floor_soc"])
        for index in range(len(axis))
    ]

    safety: dict[int, float] = {}
    trade_charge: dict[int, float] = {}
    trade_discharge: dict[int, float] = {}
    roundtrip = charge_efficiency * discharge_efficiency
    simulation_count = 0

    def simulate(*, detailed: bool = False) -> list[dict[str, Any]]:
        nonlocal simulation_count
        if check_work is not None:
            check_work()
        simulation_count += 1
        if diagnostics is not None:
            diagnostics.count("simulation_count")
        return _simulate(
            axis=axis,
            commitments=commitments,
            start_soc_percent=start_soc_percent,
            capacity_kwh=capacity_kwh,
            charge_efficiency=charge_efficiency,
            discharge_efficiency=discharge_efficiency,
            max_charge_power_w=max_charge_power_w,
            max_discharge_power_w=max_discharge_power_w,
            reserve_floor_end_soc=reserve_floor_end,
            safety=safety,
            trade_charge=trade_charge,
            trade_discharge=trade_discharge,
            check_work=check_work,
            compact=not detailed,
        )

    if diagnostics is not None:
        diagnostics.enter("safety_charging")
    initial = simulate()
    safety_needed = any(
        float(row["end_soc_percent"])
        < float(reserve_floor_end[index]) - 1e-6
        for index, row in enumerate(initial)
    )

    # Technical SOC (5%) is the normal household discharge limit above.
    # Unlike alpha.7.1.3, reserve breaches below the independently configured
    # technical + software planning target can now really be detected. Safety
    # precharge finds the cheapest feasible slot no later than each breach.
    # It never depends on the trade/export margin or the next usable-solar
    # marker and never changes the 288-slot time base.
    #
    # Re-simulate after every addition so manual commitments and target clamps
    # remain hard constraints in Combined.
    for _ in range(FORECAST_SLOTS):
        if diagnostics is not None:
            diagnostics.count("safety_iterations")
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
            break

        required_soc = float(reserve_floor_end[breach])
        need_soc = required_soc - float(route[breach]["end_soc_percent"])
        candidates = [
            index
            for index, row in enumerate(route[: breach + 1])
            if not row["manual_slots"]
            and row.get("import_price") is not None
            and float(row["charge_headroom_kwh"]) > _EPS
            and trade_charge.get(index, 0.0) <= _EPS
            and trade_discharge.get(index, 0.0) <= _EPS
        ]
        candidates.sort(
            key=lambda index: (
                float(route[index]["import_price"]),
                -index,
            )
        )

        made = False
        for index in candidates:
            max_input = float(route[index]["charge_headroom_kwh"])
            old = safety.get(index, 0.0)
            safety[index] = old + max_input
            if diagnostics is not None:
                diagnostics.count("safety_trials")
            trial = simulate()
            gain_soc = (
                float(trial[breach]["end_soc_percent"])
                - float(route[breach]["end_soc_percent"])
            )
            safety[index] = old
            if gain_soc <= 1e-6:
                continue
            add = (
                max_input
                if gain_soc <= need_soc
                else max_input * need_soc / gain_soc
            )
            safety[index] = old + add
            made = True
            break
        if not made:
            break

    # Price-shift future expensive home import with bounded route trials.
    # Every quarter participates in the price/deficit search, but a candidate
    # is simulated at most twice, instead of re-simulating each deficit-slot
    # pair in up to 64 nested passes. This remains an economic heuristic, not
    # an unsupported claim of globally optimal 72-hour scheduling.
    def route_cost(rows: Sequence[Mapping[str, Any]]) -> float:
        return sum(
            (
                float(row["grid_to_home_kwh"])
                + float(row["charge_from_grid_kwh"])
            ) * float(row.get("import_price") or 0.0)
            - float(row["solar_export_kwh"])
            * float(row.get("export_price") or 0.0)
            for row in rows
        )

    if diagnostics is not None:
        diagnostics.enter("economic_home_planning")
    economic_charge_kwh = 0.0
    economic_trial_count = 0
    route = simulate()
    current_cost = route_cost(route)
    charge_windows = sorted(
        (
            int(row["index"])
            for row in route
            if not row["manual_slots"]
            and row.get("import_price") is not None
            and safety.get(int(row["index"]), 0.0) <= _EPS
        ),
        key=lambda index: (float(route[index]["import_price"]), -index),
    )
    for index in charge_windows:
        if check_work is not None:
            check_work()
        row = route[index]
        if (
            row["manual_slots"]
            or safety.get(index, 0.0) > _EPS
            or float(row["charge_headroom_kwh"]) <= _EPS
        ):
            continue
        purchase_price = float(row["import_price"])
        # The configured minimum_trade_margin is for optional sell-to-grid
        # arbitrage, not for economically worthwhile future *home* import.
        # For home precharging, round-trip efficiency and the actual simulated
        # import/export cost decide. An extra 0.10 EUR/kWh would wrongly reject
        # valid price shifting such as 0.18 now versus 0.29 later.
        future_cost_threshold = purchase_price / roundtrip
        # Sum only future *uncovered* home demand that costs more than the
        # full cycle. Solar already credited to home/battery by simulation.
        valuable_home_need_kwh = sum(
            float(future["grid_to_home_kwh"])
            for future in route[index + 1:]
            if future.get("import_price") is not None
            and float(future["import_price"]) > future_cost_threshold
        )
        maximum = min(
            float(row["charge_headroom_kwh"]),
            valuable_home_need_kwh / roundtrip,
        )
        if maximum <= _EPS:
            continue
        previous = trade_charge.get(index, 0.0)
        best_amount = 0.0
        best_cost = current_cost
        best_route: list[dict[str, Any]] | None = None

        # Full headroom first. A smaller second probe preserves useful
        # charging when a maximum fill would crowd out later free PV.
        for amount in (maximum, maximum / 2.0):
            if amount <= _EPS or (
                best_amount > 0.0 and amount < best_amount
            ):
                continue
            trade_charge[index] = previous + amount
            if diagnostics is not None:
                diagnostics.count("economic_trials")
            trial = simulate()
            economic_trial_count += 1
            trial_cost = route_cost(trial)
            if trial_cost < best_cost - _EPS:
                best_amount = amount
                best_cost = trial_cost
                best_route = trial
        if best_route is None:
            if previous > _EPS:
                trade_charge[index] = previous
            else:
                trade_charge.pop(index, None)
            continue
        trade_charge[index] = previous + best_amount
        economic_charge_kwh += best_amount
        route = best_route
        current_cost = best_cost

    if diagnostics is not None:
        diagnostics.enter("export_trade_planning")
    # Safety does not disable trade route-wide.  Evaluate one best ordinary
    # arbitrage pair in the remaining free route.
    route = simulate()
    usable_from_start = _next_usable_solar_index(usable_pairs, 0)
    best: tuple[float, int, int] | None = None
    for charge_index, charge_row in enumerate(route[:-1]):
        if charge_row["manual_slots"]:
            continue
        if safety.get(charge_index, 0.0) > _EPS or trade_charge.get(charge_index, 0.0) > _EPS:
            continue
        if charge_row.get("import_price") is None:
            continue
        if float(charge_row["charge_headroom_kwh"]) <= _EPS:
            continue
        # Usable solar is a forecast marker, never an economic cutoff.

        cycle_cost = float(charge_row["import_price"]) / roundtrip
        for discharge_index in range(charge_index + 1, len(route)):
            discharge_row = route[discharge_index]
            if discharge_row["manual_slots"]:
                continue
            if safety.get(discharge_index, 0.0) > _EPS:
                continue
            if discharge_row.get("export_price") is None:
                continue
            margin = float(discharge_row["export_price"]) - cycle_cost
            if margin >= minimum_trade_margin_eur_per_kwh and (
                best is None or margin > best[0]
            ):
                best = (margin, charge_index, discharge_index)

    if best is not None:
        _, charge_index, discharge_index = best
        route = simulate()
        charge_input = float(route[charge_index]["charge_headroom_kwh"])
        if charge_input > _EPS:
            trade_charge[charge_index] = charge_input
            charged = simulate()
            slack_values: list[float] = []
            for row in charged[discharge_index:]:
                index = int(row["index"])
                floor_soc = float(reserve_floor_end[index])
                slack_values.append(
                    max(
                        0.0,
                        (float(row["end_soc_percent"]) - floor_soc)
                        / 100.0
                        * capacity_kwh
                        * discharge_efficiency,
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

    if diagnostics is not None:
        diagnostics.enter("final_route_and_output")
    final = simulate(detailed=True)
    candidates: list[dict[str, Any]] = []
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
    )

    for row in final:
        index = int(row["index"])
        start_reserve = reserve_profile[index]
        end_reserve = reserve_profile[index + 1]
        row.update(
            {
                "dynamic_reserve_floor_start_soc_percent": round(
                    float(start_reserve["floor_soc"]), 6
                ),
                "dynamic_reserve_floor_end_soc_percent": round(
                    float(end_reserve["floor_soc"]), 6
                ),
                "dynamic_reserve_floor_start_kwh": round(
                    float(start_reserve["floor_kwh"]), 6
                ),
                "dynamic_reserve_floor_end_kwh": round(
                    float(end_reserve["floor_kwh"]), 6
                ),
                "dynamic_need_until_usable_solar_kwh": round(
                    float(start_reserve["need_home_kwh"]), 6
                ),
                "next_usable_solar": start_reserve["next_usable_solar"],
                "solar_horizon_complete": bool(
                    start_reserve["solar_horizon_complete"]
                ),
            }
        )
        for field, candidate_type, action, reason in candidate_fields:
            energy = float(row.get(field) or 0.0)
            if energy <= _EPS:
                continue
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
    hourly = _aggregate_clock_hours(final, combined=combined)
    soc_values = [float(row["end_soc_percent"]) for row in final]
    next_candidate = candidates[0] if candidates else None
    safety_sufficient = all(
        float(row["end_soc_percent"])
        >= float(reserve_floor_end[index]) - 1e-6
        for index, row in enumerate(final)
    )
    reserve_values = [
        float(item["floor_soc"]) for item in reserve_profile[:-1]
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
            if next_candidate else "no_automatic_candidate"
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
        "start": final[0]["start"] if final else None,
        "end": final[-1]["end"] if final else None,
        "start_soc_percent": round(start_soc_percent, 6),
        "end_soc_percent": (
            final[-1]["end_soc_percent"] if final else None
        ),
        "projected_min_soc_percent": (
            round(min(soc_values), 6) if soc_values else None
        ),
        "projected_max_soc_percent": (
            round(max(soc_values), 6) if soc_values else None
        ),
        "technical_min_soc_percent": MIN_SOC_PERCENT,
        "software_reserve_percent": software_reserve_percent,
        "planner_floor_soc_percent": base_floor,
        "planner_floor_kwh": round(
            capacity_kwh * base_floor / 100.0, 6
        ),
        "dynamic_reserve_start_soc_percent": round(
            float(start_reserve["floor_soc"]), 6
        ),
        "dynamic_reserve_min_soc_percent": round(
            min(reserve_values), 6
        ),
        "dynamic_reserve_max_soc_percent": round(
            max(reserve_values), 6
        ),
        "dynamic_need_until_usable_solar_kwh": round(
            float(start_reserve["need_home_kwh"]), 6
        ),
        "planning_need_until_solar_kwh": round(float(start_reserve["need_home_kwh"]), 6),
        "hard_safety_floor_soc": base_floor,
        "usable_battery_kwh": round(max(0.0, (start_soc_percent - base_floor) * capacity_kwh / 100.0), 6),
        "unavoidable_grid_import_kwh": round(sum(float(row["grid_to_home_kwh"]) for row in final), 6),
        "economic_reserved_kwh": round(economic_charge_kwh * charge_efficiency, 6),
        "discharge_block_reason": None,
        "next_usable_solar": start_reserve["next_usable_solar"],
        "solar_horizon_complete": bool(
            start_reserve["solar_horizon_complete"]
        ),
        "solar_horizon_incomplete_slots": incomplete_slots,
        "capacity_kwh": round(capacity_kwh, 6),
        "capacity_source": "battery_input_contract_live_sensor",
        "charge_efficiency_percent": round(
            charge_efficiency * 100.0, 1
        ),
        "discharge_efficiency_percent": round(
            discharge_efficiency * 100.0, 1
        ),
        "roundtrip_efficiency_percent": round(roundtrip * 100.0, 2),
        "max_charge_power_w": max_charge_power_w,
        "max_discharge_power_w": max_discharge_power_w,
        "minimum_trade_margin_eur_per_kwh": (
            minimum_trade_margin_eur_per_kwh
        ),
        "planner_simulation_count": simulation_count,
        "planner_economic_trial_count": economic_trial_count,
        "safety_charge_needed": safety_needed,
        "safety_schedule_sufficient": safety_sufficient,
        "safety_charge_kwh": round(sum(safety.values()), 6),
        "trade_charge_kwh": round(sum(trade_charge.values()), 6),
        "trade_discharge_kwh": round(
            sum(trade_discharge.values()), 6
        ),
        "manual_commitment_count": len(commitments),
        "manual_commitment_slots": [
            int(plan["slot"]) for plan in commitments
        ],
        "usable_solar_rule": USABLE_SOLAR_RULE,
        "dynamic_reserve_rule": DYNAMIC_RESERVE_RULE,
        "peak_sale_enabled": False,
        "planner_enabled": True,
        "plan_store_writes_enabled": False,
        "scheduler_enabled": False,
        "safety_prestart_enabled": False,
        "execution_enabled": False,
        "physical_execution_enabled": False,
        "mode": "combined_planner" if combined else "automatic_planner",
    }


def build_planner_bundle(
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
    check_work: Callable[[], None] | None = None,
    stage: str = "both",
    diagnostics: PlannerDiagnostics | None = None,
    automatic_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build only the requested stage; preserve the legacy both-stage API.

    Automatic never consumes manual commitments. Combined receives those
    commitments as hard constraints. With none, it reuses Automatic exactly.
    """
    if stage not in ("automatic", "combined", "both"):
        raise ValueError("invalid_planner_stage")
    if stage == "combined" and not (automatic_snapshot or {}).get("valid"):
        raise ValueError("automatic_stage_required_for_combined")
    if diagnostics is not None:
        diagnostics.enter("model_validation")
    blockers: list[str] = []
    try:
        soc = float(start_soc_percent)
        capacity = float(capacity_kwh)
        reserve = float(software_reserve_percent)
        charge_eff = float(charge_efficiency)
        discharge_eff = float(discharge_efficiency)
        max_charge = float(max_charge_power_w)
        max_discharge = float(max_discharge_power_w)
        margin = float(minimum_trade_margin_eur_per_kwh)
    except (TypeError, ValueError):
        return {
            "status": "blocked",
            "valid": False,
            "blockers": ["planner_setting_invalid"],
            "automatic": {},
            "combined": {},
            "physical_execution_enabled": False,
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

    axis0, axis_blockers = _validate_time_axis(energy_slots, solar_slots)
    blockers.extend(axis_blockers)
    commitments, commitment_blockers = _manual_commitments(plans)
    blockers.extend(commitment_blockers)

    axis: list[dict[str, Any]] = []
    for row in axis0:
        prices = _slot_price(price_by_start, row["start"])
        if prices["import_price"] is None or prices["export_price"] is None:
            blockers.append(f"price_slot_{row['index']}_missing")
        axis.append({**row, "prices": prices})

    common_blocked = {
        "status": "blocked",
        "valid": False,
        "blockers": sorted(set(blockers)),
        "native_slots": [],
        "hourly_plan": [],
        "candidates": [],
        "candidate_count": 0,
        "native_slot_count": 0,
        "clock_hour_bucket_count": 0,
        "plan_store_writes_enabled": False,
        "scheduler_enabled": False,
        "safety_prestart_enabled": False,
        "execution_enabled": False,
        "physical_execution_enabled": False,
        "peak_sale_enabled": False,
    }
    if blockers:
        return {
            "status": "blocked",
            "valid": False,
            "blockers": sorted(set(blockers)),
            "automatic": {
                **common_blocked,
                "mode": "automatic_planner",
            },
            "combined": {
                **common_blocked,
                "manual_commitment_count": len(commitments),
                "manual_commitment_slots": [
                    int(plan["slot"]) for plan in commitments
                ],
                "mode": "combined_planner",
            },
            "physical_execution_enabled": False,
        }

    if stage in ("automatic", "both"):
        automatic = _build_planner(
            axis=axis,
            commitments=[],
            start_soc_percent=soc,
            capacity_kwh=capacity,
            software_reserve_percent=reserve,
            charge_efficiency=charge_eff,
            discharge_efficiency=discharge_eff,
            max_charge_power_w=max_charge,
            max_discharge_power_w=max_discharge,
            minimum_trade_margin_eur_per_kwh=margin,
            check_work=check_work,
            combined=False,
            diagnostics=diagnostics,
        )
    else:
        automatic = dict(automatic_snapshot or {})

    if stage in ("combined", "both"):
        if not commitments and automatic.get("valid"):
            if diagnostics is not None:
                diagnostics.enter("automatic_route_reuse")
            # No manual commitments: Combined is the same physical/economic
            # route. Avoid a second full 288-slot optimization entirely.
            combined = {
                **automatic,
                "mode": "combined_planner",
                "manual_commitment_count": 0,
                "manual_commitment_slots": [],
            }
        else:
            combined = _build_planner(
                axis=axis,
                commitments=commitments,
                start_soc_percent=soc,
                capacity_kwh=capacity,
                software_reserve_percent=reserve,
                charge_efficiency=charge_eff,
                discharge_efficiency=discharge_eff,
                max_charge_power_w=max_charge,
                max_discharge_power_w=max_discharge,
                minimum_trade_margin_eur_per_kwh=margin,
                check_work=check_work,
                combined=True,
                diagnostics=diagnostics,
            )
    else:
        combined = {}

    return {
        "status": "ready",
        "valid": bool(
            automatic.get("valid") if stage == "automatic"
            else combined.get("valid") if stage == "combined"
            else automatic.get("valid") and combined.get("valid")
        ),
        "blockers": [],
        "automatic": automatic,
        "combined": combined,
        "physical_execution_enabled": False,
    }

