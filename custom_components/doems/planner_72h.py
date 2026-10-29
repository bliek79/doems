"""Deterministic, observational 72-hour battery planning in native quarters.

All flow energies are AC kWh; ``stored_*`` values are battery-side kWh.
The model follows ordinary self-consumption down to the hardware floor.  The
additional reserve is a planning target, not an imaginary device hold command.
Explicit commands occupy disjoint time segments and temporarily replace that
passive behaviour.  This module has no Home Assistant or device dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Iterable

QUARTERS = 288
QUARTER_HOURS = 0.25
_EPS = 1e-9
_TOL = 1e-5
_FLOWS = (
    "solar_to_home_kwh", "charge_from_solar_kwh",
    "charge_from_grid_safety_kwh", "charge_from_grid_trade_kwh",
    "charge_from_grid_manual_kwh", "discharge_to_home_kwh",
    "discharge_to_grid_kwh", "discharge_to_grid_trade_kwh",
    "discharge_to_grid_manual_kwh", "grid_import_for_home_kwh",
    "solar_export_kwh", "losses_kwh",
)


def _finite(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean_number")
    result = float(value)
    if not isfinite(result):
        raise ValueError("nonfinite_number")
    return result


def _time(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("invalid_timestamp")
    return value.astimezone(timezone.utc)


def _ceil_quarter(now: datetime) -> datetime:
    floor = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
    return floor if floor == now else floor + timedelta(minutes=15)


def _empty(reason: str, manual: dict | None = None) -> dict:
    return {
        "status": "invalid", "valid": False, "reason": reason,
        "observational_only": True, "execution_enabled": False,
        "timeline": [], "slot_count": 0, "horizon_hours": None,
        "start": None, "end": None, "start_soc": None, "end_soc": None,
        "min_soc": None, "max_soc": None, "hardware_min_soc": None,
        "reserve_target_soc": None, "safety_reserve_kwh": None,
        "execution_reserve_kwh": None, "reserve_satisfied": False,
        "reserve_breach_count": None, "reserve_end_breach_count": None,
        "deadline_reserve_satisfied": False, "remaining_charge_need_kwh": None,
        "remaining_charge_need_tolerance_kwh": None,
        "totals": {key: None for key in _FLOWS},
        "trade": {
            "enabled": False, "profitable": False, "expected_margin": None,
            "effective_charge_cost": None, "best_charge_time": None,
            "best_discharge_time": None, "best_charge_price": None,
            "best_discharge_price": None, "candidate_count": 0,
            "accepted_count": 0, "reason": "invalid_input",
        },
        "manual": manual or {
            "accepted_count": 0, "skipped_count": 0, "invalid_count": 0,
            "conflicts_count": 0, "plans": [],
        },
    }


@dataclass(frozen=True)
class _Battery:
    capacity: float
    initial: float
    minimum: float
    reserve: float
    charge_eff: float
    discharge_eff: float
    charge_kw: float
    discharge_kw: float


@dataclass(frozen=True)
class _Manual:
    id: str
    action: str
    start: datetime
    end: datetime
    power_kw: float
    target: float


def _source(rows: Iterable[dict], stamps: list[datetime], kind: str) -> list:
    by_time = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"invalid_{kind}_row")
        stamp = _time(row.get("start"))
        if stamp in by_time:
            raise ValueError(f"duplicate_{kind}_timestamp")
        if kind == "price":
            imp = _finite(row.get("import_all_in"))
            exp = _finite(row.get("export_all_in"))
            label = row.get("kind")
            if not isinstance(label, str) or not label:
                raise ValueError("invalid_price_kind")
            by_time[stamp] = (imp, exp, label)
        else:
            energy = _finite(row.get("energy_kwh"))
            if energy < 0:
                raise ValueError(f"negative_{kind}_energy")
            by_time[stamp] = energy
    if any(stamp not in by_time for stamp in stamps):
        raise ValueError(f"missing_or_incomplete_288_quarter_{kind}")
    return [by_time[stamp] for stamp in stamps]


def _manual_inputs(plans, now, start, end, battery):
    diagnostic = {
        "accepted_count": 0, "skipped_count": 0, "invalid_count": 0,
        "conflicts_count": 0, "plans": [],
    }
    accepted = []
    identifiers = set()
    dormant = {"completed", "cancelled", "canceled", "expired", "disabled", "draft"}
    live = {"pending", "waiting", "scheduled", "ready", "active"}
    for raw in plans:
        item = {"id": raw.get("id") if isinstance(raw, dict) else None}
        diagnostic["plans"].append(item)
        try:
            if not isinstance(raw, dict):
                raise ValueError("invalid_manual_record")
            enabled = raw.get("enabled", True)
            if not isinstance(enabled, bool):
                raise ValueError("invalid_manual_enabled")
            lifecycle = raw.get("lifecycle_status", raw.get("lifecycle", "pending"))
            if not enabled or lifecycle in dormant:
                item.update(status="skipped", reason="inactive")
                diagnostic["skipped_count"] += 1
                continue
            if lifecycle not in live:
                raise ValueError("invalid_manual_lifecycle")
            identifier = raw.get("id")
            if not isinstance(identifier, str) or not identifier or identifier in identifiers:
                raise ValueError("invalid_or_duplicate_manual_id")
            identifiers.add(identifier)
            action = raw.get("action")
            if action not in {"charge", "discharge"}:
                raise ValueError("invalid_manual_action")
            begin = _time(raw.get("start_time"))
            power, target, runtime = map(_finite, (
                raw.get("power_w"), raw.get("target_soc"), raw.get("max_runtime_h"),
            ))
            if power <= 0 or runtime <= 0 or not battery.minimum / battery.capacity * 100 <= target <= 100:
                raise ValueError("invalid_manual_limits")
            finish = begin + timedelta(hours=runtime)
            if finish <= start or begin >= end or (begin < now and lifecycle != "active"):
                item.update(status="skipped", reason=(
                    "manual_start_window_expired" if begin < now and lifecycle != "active"
                    else "outside_horizon"
                ))
                diagnostic["skipped_count"] += 1
                continue
            plan = _Manual(identifier, action, max(start, begin), finish, power / 1000, battery.capacity * target / 100)
            accepted.append(plan)
            item.update(status="accepted", reason="projected", action=action,
                        start=plan.start.isoformat(), end=plan.end.isoformat())
            diagnostic["accepted_count"] += 1
        except (ValueError, TypeError, OverflowError) as err:
            item.update(status="invalid", reason=str(err))
            diagnostic["invalid_count"] += 1
    accepted.sort(key=lambda plan: (plan.start, plan.id))
    for previous, following in zip(accepted, accepted[1:]):
        if following.start < previous.end:
            diagnostic["conflicts_count"] += 1
    return accepted, diagnostic


class _Model:
    def __init__(self, stamps, home, solar, prices, battery, manual):
        self.stamps, self.home, self.solar, self.prices = stamps, home, solar, prices
        self.b = battery
        self.manual = manual
        self.by_slot = [[p for p in manual if p.start < t + timedelta(minutes=15) and p.end > t] for t in stamps]
        self.calls = 0

    def simulate(self, safety, trade_charge=None, trade_discharge=None, *, detail=False):
        """Replay the entire causal route; no value is borrowed from the future."""
        self.calls += 1
        trade_charge = trade_charge or {}
        trade_discharge = trade_discharge or {}
        b = self.b
        stored = b.initial
        result = []
        finished = set()
        manual_result = {p.id: {"duration_hours": 0.0, "battery_energy_kwh": 0.0,
                               "target_reached": False, "remaining_target_kwh": None,
                               "limited": False, "reasons": []} for p in self.manual}
        for index, stamp in enumerate(self.stamps):
            finish = stamp + timedelta(minutes=15)
            home_rate, solar_rate = self.home[index] * 4, self.solar[index] * 4
            direct_rate = min(home_rate, solar_rate)
            surplus, deficit = max(0.0, solar_rate - home_rate), max(0.0, home_rate - solar_rate)
            imp, exp, kind = self.prices[index]
            flows = {key: 0.0 for key in _FLOWS}
            segments = []
            starts_at = stored
            smallest, largest = stored, stored
            uncovered = 0.0
            limited = False
            actions, origins = [], []
            manual_ids = []

            def piece(begin, duration, mode="self_consumption", origin="passive", power=None, target=None, manual_id=None):
                nonlocal stored, smallest, largest, uncovered, limited
                if duration <= _EPS:
                    return
                before = stored
                values = {key: 0.0 for key in _FLOWS}
                actual_duration = duration
                input_energy = output_energy = 0.0
                reason = None
                reached = False
                if mode == "charge":
                    rate = min(max(0.0, power), b.charge_kw)
                    target = min(b.capacity, target)
                    headroom = max(0.0, target - stored)
                    actual_duration = min(duration, headroom / (rate * b.charge_eff)) if rate > _EPS else 0.0
                    input_energy = rate * actual_duration
                    solar_charge = min(surplus, rate) * actual_duration
                    values["charge_from_solar_kwh"] = solar_charge
                    values[f"charge_from_grid_{origin}_kwh"] = input_energy - solar_charge
                    values["grid_import_for_home_kwh"] = deficit * actual_duration
                    values["solar_export_kwh"] = max(0.0, surplus * actual_duration - solar_charge)
                    stored += input_energy * b.charge_eff
                    reached = stored >= target - _EPS
                    if power > b.charge_kw + _EPS:
                        reason = "charge_power_limited"
                    elif rate <= _EPS and headroom > _EPS:
                        reason = "charge_unavailable"
                elif mode == "discharge":
                    rate = min(max(0.0, power), b.discharge_kw)
                    # Deliberate battery export is blocked at a negative all-in
                    # export price, including explicit manual discharge.
                    if exp < 0 and rate > deficit + _EPS:
                        rate = min(rate, deficit)
                        reason = "negative_export_price"
                    floor = max(b.minimum, target)
                    if rate > deficit + _EPS:
                        floor = max(floor, b.reserve)
                    available = max(0.0, stored - floor)
                    actual_duration = min(duration, available * b.discharge_eff / rate) if rate > _EPS else 0.0
                    output_energy = rate * actual_duration
                    values["discharge_to_home_kwh"] = min(deficit, rate) * actual_duration
                    exported = max(0.0, output_energy - values["discharge_to_home_kwh"])
                    values["discharge_to_grid_kwh"] = exported
                    values[f"discharge_to_grid_{origin}_kwh"] = exported
                    values["grid_import_for_home_kwh"] = max(0.0, deficit * actual_duration - values["discharge_to_home_kwh"])
                    values["solar_export_kwh"] = surplus * actual_duration
                    stored -= output_energy / b.discharge_eff
                    reached = stored <= target + _EPS
                    if power > b.discharge_kw + _EPS:
                        reason = "discharge_power_limited"
                    if actual_duration < duration - _EPS and floor > target + _EPS and not reached:
                        reason = "reserve_limited"
                    if rate <= _EPS and available > _EPS and reason is None:
                        reason = "discharge_unavailable"
                else:
                    values["charge_from_solar_kwh"] = min(surplus * duration, b.charge_kw * duration, max(0.0, b.capacity - stored) / b.charge_eff)
                    input_energy = values["charge_from_solar_kwh"]
                    stored += input_energy * b.charge_eff
                    values["solar_export_kwh"] = max(0.0, surplus * duration - input_energy)
                    possible_output = min(deficit * duration, b.discharge_kw * duration)
                    output_energy = min(possible_output, max(0.0, stored - b.minimum) * b.discharge_eff)
                    values["discharge_to_home_kwh"] = output_energy
                    uncovered += max(0.0, possible_output - output_energy)
                    stored -= output_energy / b.discharge_eff
                    values["grid_import_for_home_kwh"] = max(0.0, deficit * duration - output_energy)
                values["solar_to_home_kwh"] = direct_rate * actual_duration
                values["losses_kwh"] = input_energy * (1 - b.charge_eff) + output_energy * (1 / b.discharge_eff - 1)
                if stored < -_TOL or stored > b.capacity + _TOL:
                    raise ArithmeticError("battery_energy_out_of_bounds")
                smallest, largest = min(smallest, stored), max(largest, stored)
                for key, value in values.items():
                    flows[key] += value
                if reason:
                    limited = True
                if actual_duration > _EPS:
                    action = mode if origin == "passive" else f"{origin}_{mode}"
                    if action not in actions:
                        actions.append(action)
                    if origin not in origins:
                        origins.append(origin)
                    if detail:
                        segments.append({"start": begin.isoformat(), "end": (begin + timedelta(hours=actual_duration)).isoformat(),
                                         "duration_hours": actual_duration, "action": action, "origin": origin,
                                         "manual_id": manual_id, "battery_power_w": (input_energy - output_energy) / actual_duration * 1000,
                                         "stored_start_kwh": before, "stored_end_kwh": stored,
                                         "target_soc": target / b.capacity * 100 if target is not None else None,
                                         "limited": bool(reason), "reason": reason, **values})
                if manual_id is not None:
                    progress = manual_result[manual_id]
                    progress["duration_hours"] += actual_duration
                    progress["battery_energy_kwh"] += input_energy + output_energy
                    progress["remaining_target_kwh"] = max(0.0, target - stored) if mode == "charge" else max(0.0, stored - target)
                    progress["limited"] |= bool(reason)
                    if reason and reason not in progress["reasons"]:
                        progress["reasons"].append(reason)
                    if reached or actual_duration < duration - _EPS:
                        finished.add(manual_id)
                        progress["target_reached"] |= reached
                    if manual_id not in manual_ids:
                        manual_ids.append(manual_id)
                if actual_duration < duration - _EPS:
                    piece(begin + timedelta(hours=actual_duration), duration - actual_duration)

            slot_manual = self.by_slot[index]
            if slot_manual:
                boundaries = sorted({stamp, finish, *(max(stamp, p.start) for p in slot_manual), *(min(finish, p.end) for p in slot_manual)})
                for begin, end in zip(boundaries, boundaries[1:]):
                    current = next((p for p in slot_manual if p.start <= begin < p.end), None)
                    duration = (end - begin).total_seconds() / 3600
                    if current is None or current.id in finished:
                        piece(begin, duration)
                    else:
                        piece(begin, duration, current.action, "manual", current.power_kw, current.target, current.id)
            else:
                duration = safety.get(index, 0.0)
                origin = "safety"
                mode, target, power = "charge", b.capacity, b.charge_kw
                if index in trade_charge:
                    duration, origin = trade_charge[index], "trade"
                elif index in trade_discharge:
                    duration, origin, mode, target, power = trade_discharge[index], "trade", "discharge", b.reserve, b.discharge_kw
                if duration > _EPS:
                    piece(stamp, duration, mode, origin, power, target)
                piece(stamp + timedelta(hours=duration), QUARTER_HOURS - duration)
            reserve_gap = max(0.0, b.reserve - stored)
            reserve_min_gap = max(0.0, b.reserve - smallest)
            row = {"stored_end_kwh": stored, "stored_start_kwh": starts_at,
                   "soc_start": starts_at / b.capacity * 100, "soc_end": stored / b.capacity * 100,
                   "min_soc": smallest / b.capacity * 100, "max_soc": largest / b.capacity * 100,
                   "uncovered_home_kwh": uncovered, "reserve_gap_kwh": reserve_gap,
                   "reserve_min_gap_kwh": reserve_min_gap,
                   "shortfall_kwh": reserve_gap / b.charge_eff + uncovered / (b.charge_eff * b.discharge_eff),
                   "limited": limited or reserve_min_gap > _TOL or uncovered > _TOL,
                   "cost": (flows["grid_import_for_home_kwh"] + sum(flows[f"charge_from_grid_{x}_kwh"] for x in ("safety", "trade", "manual"))) * imp - (flows["solar_export_kwh"] + flows["discharge_to_grid_kwh"]) * exp,
                   **flows}
            if detail:
                row.update(start=stamp.isoformat(), end=finish.isoformat(), duration_hours=QUARTER_HOURS,
                           home_kwh=self.home[index], solar_kwh=self.solar[index],
                           import_all_in=imp, export_all_in=exp, kind=kind,
                           action="+".join(actions) or "self_consumption", origin="+".join(origins) or "passive",
                           manual_ids=manual_ids, segments=segments)
            result.append(row)
        for plan in self.manual:
            progress = manual_result[plan.id]
            if plan.end <= self.stamps[-1] + timedelta(minutes=15) and not progress["target_reached"]:
                progress["limited"] = True
                if "maximum_runtime_before_target" not in progress["reasons"]:
                    progress["reasons"].append("maximum_runtime_before_target")
        return result, manual_result


def _need(row, battery):
    return row["reserve_gap_kwh"] + row["uncovered_home_kwh"] / battery.discharge_eff


def _remaining_battery_need(trace, battery):
    """Return the route shortfall in stored kWh, before charging losses."""
    return (max(row["reserve_gap_kwh"] for row in trace)
            + sum(row["uncovered_home_kwh"] for row in trace) / battery.discharge_eff)


def _protected_ceiling(previous, reference):
    """Spend one tolerance budget, including any pre-existing small residue."""
    return min(previous + _TOL, max(reference, _TOL))


def _safety_schedule(model):
    schedule = {}
    trace, _ = model.simulate(schedule)
    if model.b.charge_kw <= _EPS:
        return schedule, trace
    blocked = set()
    # Each successful iteration fills one window or resolves a deadline.  The
    # additional N iterations let physically impossible deadlines be recorded
    # without preventing later independent, feasible charging.
    for _ in range(QUARTERS * 3):
        deadline = next((i for i, row in enumerate(trace) if i not in blocked and _need(row, model.b) > _TOL), None)
        if deadline is None:
            break
        need = _need(trace[deadline], model.b)
        last_full = max((i for i in range(deadline) if trace[i]["max_soc"] >= 100 - _TOL), default=-1)
        candidates = [i for i in range(last_full + 1, deadline + 1) if not model.by_slot[i] and schedule.get(i, 0.0) < QUARTER_HOURS - _EPS]
        candidates.sort(key=lambda i: (model.prices[i][0], -i))
        improved = False
        for candidate in candidates:
            trial_schedule = {**schedule, candidate: QUARTER_HOURS}
            trial, _ = model.simulate(trial_schedule)
            gain = need - _need(trial[deadline], model.b)
            if gain <= _TOL or any(_need(trial[i], model.b) > _need(trace[i], model.b) + _TOL for i in range(deadline)):
                continue
            if _need(trial[deadline], model.b) <= _TOL:
                low, high = schedule.get(candidate, 0.0), QUARTER_HOURS
                def balance(row):
                    return row["stored_end_kwh"] - model.b.reserve - row["uncovered_home_kwh"] / model.b.discharge_eff
                low_value, high_value = balance(trace[deadline]), balance(trial[deadline])
                target = _TOL / 8
                # The route is affine between physical boundaries.  A checked
                # interpolation normally solves a deadline in one replay; the
                # bounded bracket also handles capacity/target transitions.
                for _ in range(12):
                    if high - low <= 1e-9:
                        break
                    ratio = (target - low_value) / (high_value - low_value) if high_value > low_value + _EPS else 0.5
                    middle = low + (high - low) * min(0.99, max(0.01, ratio))
                    probe, _ = model.simulate({**schedule, candidate: middle})
                    value = balance(probe[deadline])
                    if value >= -_EPS:
                        high = middle
                        high_value = value
                        if value <= _TOL / 4:
                            break
                    else:
                        low = middle
                        low_value = value
                trial_schedule[candidate] = high
                check, _ = model.simulate(trial_schedule)
                if _need(check[deadline], model.b) <= _TOL and not any(_need(check[i], model.b) > _need(trace[i], model.b) + _TOL for i in range(deadline)):
                    trial = check
                else:
                    trial_schedule[candidate] = QUARTER_HOURS
            schedule, trace = trial_schedule, trial
            improved = True
            break
        if not improved:
            blocked.add(deadline)
    return schedule, trace


def _trade_schedule(model, safety, baseline, minimum_margin, enabled):
    """Bounded secondary improvement, with no assumed passive holding power.

    Search candidates by theoretical margin, then check their complete physical
    route and actual incremental cash flows.  This is deliberately a bounded
    deterministic heuristic; it does not claim a global economic optimum.
    """
    diagnostic = {"enabled": enabled, "profitable": False, "expected_margin": None,
                  "effective_charge_cost": None, "best_charge_time": None,
                  "best_discharge_time": None, "best_charge_price": None,
                  "best_discharge_price": None, "candidate_count": 0,
                  "accepted_count": 0, "reason": "disabled" if not enabled else "no_safe_profitable_trade",
                  "search_method": "bounded_sequential_route_comparison", "globally_optimal": False,
                  "evaluated_count": 0, "search_limited": False,
                  "margin_basis": "best_accepted_incremental_cash_saving_per_exported_ac_kwh",
                  "total_horizon_cost_saving": 0.0, "total_traded_export_kwh": 0.0,
                  "aggregate_expected_margin": None}
    charges, discharges = {}, {}
    if not enabled or model.b.discharge_kw <= _EPS:
        return charges, discharges, diagnostic
    roundtrip = model.b.charge_eff * model.b.discharge_eff
    candidates = []
    available = [i for i in range(QUARTERS) if not model.by_slot[i] and i not in safety]
    for sell in available:
        price = model.prices[sell][1]
        if price < 0:
            continue
        if price >= minimum_margin and baseline[sell]["stored_start_kwh"] > model.b.reserve + _TOL:
            candidates.append((price, None, sell))
        if model.b.charge_kw > _EPS:
            for buy in available:
                if buy >= sell:
                    break
                margin = price - model.prices[buy][0] / roundtrip
                if margin >= minimum_margin:
                    candidates.append((margin, buy, sell))
    candidates.sort(key=lambda item: (-item[0], item[2], -1 if item[1] is None else item[1]))
    diagnostic["candidate_count"] = len(candidates)
    # Bound actual full-route simulations independently of the input values.
    direct = [item for item in candidates if item[1] is None]
    paired = [item for item in candidates if item[1] is not None]
    # Neither family may monopolize the finite route-comparison budget.
    search = direct[:32] + paired[:32]
    if len(search) < 64:
        search += (direct[32:] + paired[32:])[:64 - len(search)]
    search.sort(key=lambda item: (-item[0], item[2], -1 if item[1] is None else item[1]))
    diagnostic["search_limited"] = len(candidates) > len(search)
    current = baseline
    _, baseline_manual = model.simulate(safety)
    current_manual = baseline_manual
    baseline_need = _remaining_battery_need(baseline, model.b)
    current_need = baseline_need
    # An accepted purchase intentionally imports the home's demand during its
    # charge segment.  Freeze that allowance once; subsequent trades must not
    # spend another tolerance against the already changed route.
    home_import_reference = [row["grid_import_for_home_kwh"] for row in baseline]
    manual_actions = {plan.id: plan.action for plan in model.manual}

    def protected(trial, before, buy, manual_trial):
        # The original protected route owns one numerical tolerance budget.
        # Comparing only with the last accepted trade lets that budget accrue
        # once per trade.  Also protect the aggregate household shortfall so
        # tiny gaps in different quarters cannot accumulate into a new need.
        aggregate_safe = _remaining_battery_need(trial, model.b) <= _protected_ceiling(current_need, baseline_need)
        route_safe = aggregate_safe and all(
            row["uncovered_home_kwh"] <= _protected_ceiling(old["uncovered_home_kwh"], baseline[i]["uncovered_home_kwh"])
            and row["reserve_gap_kwh"] <= _protected_ceiling(old["reserve_gap_kwh"], baseline[i]["reserve_gap_kwh"])
            and row["reserve_min_gap_kwh"] <= _protected_ceiling(old["reserve_min_gap_kwh"], baseline[i]["reserve_min_gap_kwh"])
            # Conservatively retain every PV-storage opportunity already in
            # the protected route.  A trade purchase cannot displace free PV;
            # necessary safety charges and manual instructions are unaffected.
            and row["charge_from_solar_kwh"] >= max(old["charge_from_solar_kwh"], baseline[i]["charge_from_solar_kwh"]) - _TOL
            and (i == buy or row["grid_import_for_home_kwh"] <= _protected_ceiling(old["grid_import_for_home_kwh"], home_import_reference[i]))
            for i, (row, old) in enumerate(zip(trial, before))
        )
        manual_safe = all(
            (not old["target_reached"] or manual_trial[identifier]["target_reached"])
            and (manual_trial[identifier]["remaining_target_kwh"] or 0.0) <= _protected_ceiling(old["remaining_target_kwh"] or 0.0, baseline_manual[identifier]["remaining_target_kwh"] or 0.0)
            and (manual_actions[identifier] != "discharge" or manual_trial[identifier]["battery_energy_kwh"] >= max(old["battery_energy_kwh"], baseline_manual[identifier]["battery_energy_kwh"]) - _TOL)
            for identifier, old in current_manual.items()
        )
        return route_safe and manual_safe

    for _theoretical_margin, buy, sell in search:
        if sell in charges or sell in discharges or (buy is not None and (buy in charges or buy in discharges)):
            continue
        diagnostic["evaluated_count"] += 1
        candidate_charges = dict(charges)
        if buy is not None:
            candidate_charges[buy] = QUARTER_HOURS
        candidate_discharges = {**discharges, sell: QUARTER_HOURS}
        trial, trial_manual = model.simulate(safety, candidate_charges, candidate_discharges)
        if not protected(trial, current, buy, trial_manual):
            low, high = 0.0, QUARTER_HOURS
            for _ in range(14):
                middle = (low + high) / 2
                probe, probe_manual = model.simulate(safety, candidate_charges, {**discharges, sell: middle})
                if protected(probe, current, buy, probe_manual):
                    low = middle
                else:
                    high = middle
            if low <= _EPS:
                continue
            candidate_discharges[sell] = low
            trial, trial_manual = model.simulate(safety, candidate_charges, candidate_discharges)
        if buy is not None:
            # Do not buy a full quarter merely because a tiny sale was possible.
            low, high = 0.0, QUARTER_HOURS
            sale = trial[sell]["discharge_to_grid_trade_kwh"]
            for _ in range(14):
                middle = (low + high) / 2
                probe, probe_manual = model.simulate(safety, {**charges, buy: middle}, candidate_discharges)
                if protected(probe, current, buy, probe_manual) and probe[sell]["discharge_to_grid_trade_kwh"] >= sale - _TOL:
                    high = middle
                else:
                    low = middle
            candidate_charges[buy] = high
            trial, trial_manual = model.simulate(safety, candidate_charges, candidate_discharges)
        exported = sum(row["discharge_to_grid_trade_kwh"] for row in trial) - sum(row["discharge_to_grid_trade_kwh"] for row in current)
        saving = sum(row["cost"] for row in current) - sum(row["cost"] for row in trial)
        if exported <= _TOL or not protected(trial, current, buy, trial_manual) or saving < exported * minimum_margin - _EPS:
            continue
        charges, discharges, current = candidate_charges, candidate_discharges, trial
        current_manual = trial_manual
        current_need = _remaining_battery_need(current, model.b)
        if buy is not None:
            home_import_reference[buy] = current[buy]["grid_import_for_home_kwh"]
        actual_margin = saving / exported
        if diagnostic["expected_margin"] is None or actual_margin > diagnostic["expected_margin"] + _EPS:
            diagnostic.update(expected_margin=actual_margin,
                              effective_charge_cost=model.prices[buy][0] / roundtrip if buy is not None else None,
                              best_charge_time=model.stamps[buy].isoformat() if buy is not None else None,
                              best_discharge_time=model.stamps[sell].isoformat(),
                              best_charge_price=model.prices[buy][0] if buy is not None else None,
                              best_discharge_price=model.prices[sell][1])
        diagnostic.update(profitable=True, reason="safe_profitable_route_improvement")
        diagnostic["total_horizon_cost_saving"] += saving
        diagnostic["total_traded_export_kwh"] += exported
        diagnostic["aggregate_expected_margin"] = diagnostic["total_horizon_cost_saving"] / diagnostic["total_traded_export_kwh"]
        diagnostic["accepted_count"] += 1
    return charges, discharges, diagnostic


def calculate_plan72(home_slots, solar_slots, price_slots, *, now, soc_percent,
                     capacity_kwh, min_soc_percent, reserve_percent,
                     charge_efficiency=0.92, discharge_efficiency=0.92,
                     max_charge_power_w, max_discharge_power_w,
                     minimum_trade_margin=0.10, trade_enabled=True, manual_plans=()):
    """Return a complete observational plan or a structured invalid result.

    Forecast rows use timezone-aware ``start`` and ``energy_kwh``; prices use
    ``import_all_in``, ``export_all_in`` and a nonempty ``kind``.  Hourly prices
    must be normalized by the existing price adapter before entering this API.
    Manual powers are total battery AC setpoints.  Forecasts are treated as
    uniform rates within each quarter when a manual or automatic window splits
    it.  Active manual continuation starts from measured SOC without crediting
    past energy.  The supplied window is a maximum duration, not a target tracker.
    """
    try:
        now = _time(now)
        start = _ceil_quarter(now)
        stamps = [start + timedelta(minutes=15 * i) for i in range(QUARTERS)]
        soc, capacity, minimum, reserve, eta_in, eta_out, charge_w, discharge_w, margin = map(_finite, (
            soc_percent, capacity_kwh, min_soc_percent, reserve_percent,
            charge_efficiency, discharge_efficiency, max_charge_power_w,
            max_discharge_power_w, minimum_trade_margin,
        ))
        if (not 0 <= soc <= 100 or capacity <= 0 or not 0 <= minimum < 100
                or not 0 <= reserve <= 100 - minimum or not 0 < eta_in <= 1
                or not 0 < eta_out <= 1 or charge_w < 0 or discharge_w < 0 or margin < 0
                or not isinstance(trade_enabled, bool)):
            return _empty("invalid_battery_configuration")
        battery = _Battery(capacity, capacity * soc / 100, capacity * minimum / 100,
                           capacity * (minimum + reserve) / 100, eta_in, eta_out,
                           charge_w / 1000, discharge_w / 1000)
        home = _source(home_slots, stamps, "home")
        solar = _source(solar_slots, stamps, "solar")
        prices = _source(price_slots, stamps, "price")
        manual, manual_diagnostic = _manual_inputs(manual_plans, now, start, start + timedelta(hours=72), battery)
        if manual_diagnostic["invalid_count"] or manual_diagnostic["conflicts_count"]:
            return _empty("invalid_or_overlapping_manual_plans", manual_diagnostic)
    except (ValueError, TypeError, OverflowError) as err:
        return _empty(str(err) or "invalid_input")
    model = _Model(stamps, home, solar, prices, battery, manual)
    safety, baseline = _safety_schedule(model)
    trade_charge, trade_discharge, trade = _trade_schedule(model, safety, baseline, margin, trade_enabled)
    timeline, manual_progress = model.simulate(safety, trade_charge, trade_discharge, detail=True)
    for item in manual_diagnostic["plans"]:
        if item.get("status") == "accepted" and isinstance(item["id"], str) and item["id"] in manual_progress:
            item.update(manual_progress[item["id"]])
    totals = {key: sum(row[key] for row in timeline) for key in _FLOWS}
    reserve_end_breaches = sum(row["reserve_gap_kwh"] > _TOL for row in timeline)
    reserve_breaches = sum(row["reserve_min_gap_kwh"] > _TOL for row in timeline)
    remaining_battery = _remaining_battery_need(timeline, battery)
    physical_shortfall = remaining_battery > _TOL
    # Preserve the raw AC requirement, even below tolerance.  Status and reason
    # both use the same stored-energy tolerance as the safety scheduler; apply
    # charging efficiency once when publishing the AC energy and its tolerance.
    remaining = remaining_battery / eta_in
    manual_limited = any(item.get("limited") for item in manual_diagnostic["plans"])
    limited = reserve_breaches > 0 or physical_shortfall or manual_limited
    reason = ("remaining_physical_shortfall" if physical_shortfall else
              "manual_plan_limited" if manual_limited else
              "reserve_breach_in_projection" if reserve_breaches else "sequential_plan_ready")
    return {
        "status": "limited" if limited else "ready", "valid": True,
        "reason": reason,
        "observational_only": True, "execution_enabled": False,
        "timeline": timeline, "slot_count": QUARTERS, "horizon_hours": 72.0,
        "start": start.isoformat(), "end": (start + timedelta(hours=72)).isoformat(),
        "start_soc": soc, "end_soc": timeline[-1]["soc_end"],
        "min_soc": min(row["min_soc"] for row in timeline),
        "max_soc": max(row["max_soc"] for row in timeline),
        "hardware_min_soc": minimum, "reserve_target_soc": minimum + reserve,
        "safety_reserve_kwh": capacity * reserve / 100,
        "execution_reserve_kwh": battery.reserve,
        "reserve_satisfied": reserve_breaches == 0,
        "reserve_breach_count": reserve_breaches,
        "reserve_end_breach_count": reserve_end_breaches,
        "deadline_reserve_satisfied": reserve_end_breaches == 0,
        "reserve_breach_basis": "minimum_within_each_quarter_including_measured_start_soc",
        "remaining_charge_need_kwh": remaining,
        "remaining_charge_need_tolerance_kwh": _TOL / eta_in,
        "remaining_charge_need_basis": "maximum_reserve_gap_plus_uncovered_household_ac_energy",
        "totals": totals, "trade": trade, "manual": manual_diagnostic,
        "projection_count": model.calls,
        "model": "deterministic_segmented_self_consumption",
        "globally_optimal": False,
    }
