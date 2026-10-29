"""Deterministic, observational 72-hour battery planning in native quarters.

All flow energies are AC kWh; ``stored_*`` values are battery-side kWh.
The model follows ordinary self-consumption down to the hardware floor.  The
additional reserve is a planning target, not an imaginary device hold command.
Explicit commands occupy disjoint time segments and temporarily replace that
passive behaviour.  This module has no Home Assistant or device dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from hashlib import sha256
import json
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
        "action_windows": [], "action_window_count": 0,
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


@dataclass(frozen=True)
class _Window:
    id: str
    action: str
    origin: str
    start: datetime
    end: datetime
    power_kw: float
    target: float

    @property
    def power_start(self):
        return self.start + timedelta(minutes=2)


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

    def simulate(self, safety, trade_charge=None, trade_discharge=None, *, detail=False, windows=()):
        """Replay the entire causal route; no value is borrowed from the future."""
        self.calls += 1
        trade_charge = trade_charge or {}
        trade_discharge = trade_discharge or {}
        b = self.b
        stored = b.initial
        result = []
        finished = set()
        window_finished = set()
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

            def piece(begin, duration, mode="self_consumption", origin="passive", power=None, target=None, manual_id=None, window_id=None):
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
                elif mode == "preparation":
                    # Conservative fixed-zero-power handoff: PV supplies the
                    # home first, surplus exports, home deficit imports.
                    values["grid_import_for_home_kwh"] = deficit * duration
                    values["solar_export_kwh"] = surplus * duration
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
                                         "manual_id": manual_id, "window_id": window_id, "battery_power_w": (input_energy - output_energy) / actual_duration * 1000,
                                         "stored_start_kwh": before, "stored_end_kwh": stored,
                                         "target_soc": target / b.capacity * 100 if target is not None else None,
                                         "limited": bool(reason), "reason": reason, **values})
                if window_id is not None and (reached or actual_duration < duration - _EPS):
                    window_finished.add(window_id)
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
            elif windows:
                current_windows = [w for w in windows if w.start < finish and w.end > stamp]
                boundaries = sorted({stamp, finish,
                    *(max(stamp, w.start) for w in current_windows),
                    *(min(finish, w.end) for w in current_windows),
                    *(w.power_start for w in current_windows if stamp < w.power_start < finish)})
                for begin, end in zip(boundaries, boundaries[1:]):
                    current = next((w for w in current_windows if w.start <= begin < w.end), None)
                    duration = (end-begin).total_seconds()/3600
                    if current is None or current.id in window_finished:
                        piece(begin, duration)
                    elif begin < current.power_start:
                        piece(begin, duration, "preparation", current.origin, window_id=current.id)
                    else:
                        piece(begin, duration, current.action, current.origin,
                              current.power_kw, current.target, window_id=current.id)
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


def _window_free(model, window, others):
    return (window.end-window.start <= timedelta(hours=12)
            and window.start >= model.stamps[0]
            and window.end <= model.stamps[-1]+timedelta(minutes=15)
            and not any(p.start < window.end and p.end > window.start for p in model.manual)
            and not any(w.start < window.end and w.end > window.start for w in others))


def _safety_windows(model):
    """Resolve chronological needs using complete quarter-aligned commands.

    Extend an existing charge first, then open a price-ranked earlier window.
    Power is searched in hardware-bounded 10 W steps, not in pulse seconds.
    Every accepted edit is replayed through the SAME causal simulator.
    """
    windows = []
    trace, _ = model.simulate({})
    blocked = set()
    diagnostics = {"search_limited": False, "replay_budget": 4096,
                   "minimum_window_minutes": 15, "maximum_window_hours": 12,
                   "preparation_minutes": 2, "minimum_power_w": 100,
                   "power_step_w": 10, "method": "bounded_chronological_window_replay"}
    max_step = int(model.b.charge_kw*1000//10)
    if max_step < 10:
        diagnostics["reason"] = "no_representable_charge_power"
        return windows, trace, diagnostics
    for _ in range(QUARTERS*3):
        if model.calls >= diagnostics["replay_budget"]:
            diagnostics["search_limited"] = True
            break
        deadline = next((i for i,r in enumerate(trace) if i not in blocked and _need(r,model.b)>_TOL),None)
        if deadline is None:
            break
        finish = model.stamps[deadline]+timedelta(minutes=15)
        edits = []
        # Reuse/extend the most recent existing safety window when possible.
        for old in reversed(windows):
            if old.origin != "safety" or old.start > model.stamps[deadline]:
                continue
            others = [w for w in windows if w.id != old.id]
            # Increase an existing cheap charge before extending its time
            # into later prices: more useful stored energy, fewer switches.
            stronger = replace(old,power_kw=max_step/100)
            if _window_free(model,stronger,others):
                edits.append((stronger,others))
            candidate = replace(old, end=max(finish,old.end),power_kw=max_step/100)
            if candidate.end != old.end and _window_free(model,candidate,others):
                edits.append((candidate,others))
            if len(edits)>=4:
                break
        # No fixed daily action-count limit. Search a bounded set of the
        # cheapest unoccupied full quarters that precede this actual deadline.
        cheap = sorted(range(deadline+1),key=lambda i:(model.prices[i][0],-i))
        # The cheapest earlier quarters may be unusable due to capacity.
        # Always reserve candidate coverage for the latest deadline quarters.
        available = list(dict.fromkeys(cheap[:32]+list(range(deadline,max(-1,deadline-16),-1))))
        added = 0
        for i in available:
            candidate = _Window("safety_"+model.stamps[i].isoformat(),"charge","safety",
                                model.stamps[i],model.stamps[i]+timedelta(minutes=15),
                                max_step/100,model.b.capacity)
            if not _window_free(model,candidate,windows):
                continue
            edits.append((candidate,list(windows)))
            added+=1
            if added>=48:
                break
        improved = False
        for candidate,others in edits:
            if model.calls+12 >= diagnostics["replay_budget"]:
                diagnostics["search_limited"] = True
                break
            begin_index = int((candidate.start-model.stamps[0]).total_seconds()/900)
            stored_before = trace[begin_index]["stored_start_kwh"]
            available_hours = (candidate.end-candidate.power_start).total_seconds()/3600
            # A practical charge occupies the whole power phase. Prevent
            # capacity clipping/early target stop from turning the power
            # search non-monotonic or recreating a short charge pulse.
            local_max_step = min(max_step,int(max(0.,model.b.capacity-stored_before)
                / model.b.charge_eff / available_hours * 100 + _EPS))
            if local_max_step < 10:
                continue
            candidate = replace(candidate,power_kw=local_max_step/100)
            trial,_ = model.simulate({},windows=others+[candidate])
            before_need = _need(trace[deadline],model.b)
            if before_need-_need(trial[deadline],model.b)<=_TOL:
                continue
            if any(_need(trial[i],model.b)>_need(trace[i],model.b)+_TOL for i in range(deadline)):
                continue
            if _need(trial[deadline],model.b)<=_TOL:
                low,high=10,local_max_step
                # Integer search prevents accumulated rounding outside limits.
                while low<high:
                    middle=(low+high)//2
                    probe,_=model.simulate({},windows=others+[replace(candidate,power_kw=middle/100)])
                    if (_need(probe[deadline],model.b)<=_TOL/4
                            and not any(_need(probe[i],model.b)>_need(trace[i],model.b)+_TOL for i in range(deadline))):
                        high=middle
                    else:
                        low=middle+1
                candidate=replace(candidate,power_kw=high/100)
                trial,_=model.simulate({},windows=others+[candidate])
            windows=sorted(others+[candidate],key=lambda w:w.start)
            trace=trial
            improved=True
            break
        if not improved:
            blocked.add(deadline)
        if diagnostics["search_limited"]:
            break
    windows,trace = _compact_windows(model,windows,trace)
    diagnostics["replays_used"] = model.calls
    diagnostics["unresolved_deadlines"] = len(blocked)
    return windows,trace,diagnostics


def _trade_windows(model, windows, baseline, minimum_margin, enabled):
    """Secondary route-cost improvement using the same practical windows.

    A fixed reference owns the single Alpha52 numerical tolerance budget.
    No forecast, home-import hold assumption, or second SOC engine is added.
    """
    diagnostic = {"enabled":enabled,"profitable":False,"expected_margin":None,
        "effective_charge_cost":None,"best_charge_time":None,"best_discharge_time":None,
        "best_charge_price":None,"best_discharge_price":None,"candidate_count":0,
        "accepted_count":0,"reason":"disabled" if not enabled else "no_safe_profitable_trade",
        "search_method":"bounded_practical_window_route_comparison","globally_optimal":False,
        "evaluated_count":0,"search_limited":False,
        "margin_basis":"best_accepted_incremental_cash_saving_per_exported_ac_kwh",
        "total_horizon_cost_saving":0.,"total_traded_export_kwh":0.,"aggregate_expected_margin":None}
    max_out=int(model.b.discharge_kw*1000//10)
    max_in=int(model.b.charge_kw*1000//10)
    if not enabled or max_out<10:
        return windows,diagnostic
    current=baseline
    _,reference_manual=model.simulate({},windows=windows)
    current_manual=reference_manual
    reference_need=_remaining_battery_need(baseline,model.b)
    import_reference=[r["grid_import_for_home_kwh"] for r in baseline]
    manual_actions={p.id:p.action for p in model.manual}
    def make(i,action,step):
        return _Window("trade_"+action+"_"+model.stamps[i].isoformat(),action,"trade",
            model.stamps[i],model.stamps[i]+timedelta(minutes=15),step/100,
            model.b.capacity if action=="charge" else model.b.reserve)
    available=[i for i in range(QUARTERS) if _window_free(model,make(i,"discharge",max_out),windows)]
    rt=model.b.charge_eff*model.b.discharge_eff
    candidates=[]
    for sell in available:
        price=model.prices[sell][1]
        if price<0:
            continue
        if price>=minimum_margin and baseline[sell]["stored_start_kwh"]>model.b.reserve+_TOL:
            candidates.append((price,None,sell))
        if max_in>=10:
            for buy in available:
                if buy>=sell:
                    break
                margin=price-model.prices[buy][0]/rt
                if margin>=minimum_margin:
                    candidates.append((margin,buy,sell))
    candidates.sort(key=lambda x:(-x[0],x[2],-1 if x[1] is None else x[1]))
    diagnostic["candidate_count"]=len(candidates)
    direct=[x for x in candidates if x[1] is None]
    pairs=[x for x in candidates if x[1] is not None]
    search=sorted(direct[:24]+pairs[:24],key=lambda x:(-x[0],x[2]))
    diagnostic["search_limited"]=len(search)<len(candidates)
    def protected(trial,before,buy,manual_trial):
        if _remaining_battery_need(trial,model.b)>_protected_ceiling(_remaining_battery_need(before,model.b),reference_need):
            return False
        for i,(r,old) in enumerate(zip(trial,before)):
            for key in ("reserve_gap_kwh","reserve_min_gap_kwh","uncovered_home_kwh"):
                if r[key]>_protected_ceiling(old[key],baseline[i][key]):
                    return False
            if r["charge_from_solar_kwh"]<max(old["charge_from_solar_kwh"],baseline[i]["charge_from_solar_kwh"])-_TOL:
                return False
            if i!=buy and r["grid_import_for_home_kwh"]>_protected_ceiling(old["grid_import_for_home_kwh"],import_reference[i]):
                return False
        for identifier,old in current_manual.items():
            value=manual_trial[identifier]
            if old["target_reached"] and not value["target_reached"]:
                return False
            if (value["remaining_target_kwh"] or 0)>_protected_ceiling(old["remaining_target_kwh"] or 0,reference_manual[identifier]["remaining_target_kwh"] or 0):
                return False
            if manual_actions[identifier]=="discharge" and value["battery_energy_kwh"]<max(old["battery_energy_kwh"],reference_manual[identifier]["battery_energy_kwh"])-_TOL:
                return False
        return True
    for _,buy,sell in search:
        sale=make(sell,"discharge",max_out)
        purchase=make(buy,"charge",max_in) if buy is not None else None
        if not _window_free(model,sale,windows) or (purchase and not _window_free(model,purchase,windows)):
            continue
        diagnostic["evaluated_count"]+=1
        additions=([purchase] if purchase else [])
        trial,progress=model.simulate({},windows=windows+additions+[sale])
        if not protected(trial,current,buy,progress):
            low,high=9,max_out
            while low<high:
                middle=(low+high+1)//2
                probe,probe_progress=model.simulate({},windows=windows+additions+[replace(sale,power_kw=middle/100)])
                if protected(probe,current,buy,probe_progress):
                    low=middle
                else:
                    high=middle-1
            if low<10:
                continue
            sale=replace(sale,power_kw=low/100)
            trial,progress=model.simulate({},windows=windows+additions+[sale])
        # Reserve/capacity clipping must be resolved by reducing the setpoint,
        # not by accepting an optional export pulse that stops early.
        delivered_output=trial[sell]["discharge_to_home_kwh"]+trial[sell]["discharge_to_grid_trade_kwh"]
        complete_hours=(sale.end-sale.power_start).total_seconds()/3600
        deliverable_step=int((delivered_output/complete_hours*100+_EPS)//1)
        if deliverable_step < sale.power_kw*100-1e-7:
            if deliverable_step<10:
                continue
            sale=replace(sale,power_kw=deliverable_step/100)
            trial,progress=model.simulate({},windows=windows+additions+[sale])
        if purchase:
            sale_energy=trial[sell]["discharge_to_grid_trade_kwh"]
            low,high=10,max_in
            while low<high:
                middle=(low+high)//2
                probe,probe_progress=model.simulate({},windows=windows+[replace(purchase,power_kw=middle/100),sale])
                if (protected(probe,current,buy,probe_progress)
                        and probe[sell]["discharge_to_grid_trade_kwh"]>=sale_energy-_TOL):
                    high=middle
                else:
                    low=middle+1
            purchase=replace(purchase,power_kw=high/100)
            additions=[purchase]
            trial,progress=model.simulate({},windows=windows+additions+[sale])
        exported=sum(r["discharge_to_grid_trade_kwh"] for r in trial)-sum(r["discharge_to_grid_trade_kwh"] for r in current)
        saving=sum(r["cost"] for r in current)-sum(r["cost"] for r in trial)
        if exported<=_TOL or not protected(trial,current,buy,progress) or saving<exported*minimum_margin-_EPS:
            continue
        # Reject optional trades which hit their target before their complete
        # planned power phase; reduce power rather than create a tiny pulse.
        detailed,_=model.simulate({},windows=windows+additions+[sale],detail=True)
        if any(sum(s["duration_hours"] for r in detailed for s in r["segments"]
                   if s.get("window_id")==w.id and s["action"] in {"safety_charge","trade_charge","trade_discharge"})
               < (w.end-w.power_start).total_seconds()/3600-1e-7 for w in windows+additions+[sale]):
            continue
        windows=sorted(windows+additions+[sale],key=lambda w:w.start)
        current,current_manual=trial,progress
        if buy is not None:
            import_reference[buy]=current[buy]["grid_import_for_home_kwh"]
        actual=saving/exported
        if diagnostic["expected_margin"] is None or actual>diagnostic["expected_margin"]+_EPS:
            diagnostic.update(expected_margin=actual,effective_charge_cost=model.prices[buy][0]/rt if buy is not None else None,
                best_charge_time=model.stamps[buy].isoformat() if buy is not None else None,
                best_discharge_time=model.stamps[sell].isoformat(),best_charge_price=model.prices[buy][0] if buy is not None else None,
                best_discharge_price=model.prices[sell][1])
        diagnostic.update(profitable=True,reason="safe_profitable_route_improvement")
        diagnostic["accepted_count"]+=1
        diagnostic["total_horizon_cost_saving"]+=saving
        diagnostic["total_traded_export_kwh"]+=exported
        diagnostic["aggregate_expected_margin"]=diagnostic["total_horizon_cost_saving"]/diagnostic["total_traded_export_kwh"]
    windows,current = _compact_windows(model,windows,current,trading=True)
    if diagnostic["profitable"]:
        diagnostic["total_horizon_cost_saving"] = sum(r["cost"] for r in baseline)-sum(r["cost"] for r in current)
        diagnostic["total_traded_export_kwh"] = sum(r["discharge_to_grid_trade_kwh"] for r in current)-sum(r["discharge_to_grid_trade_kwh"] for r in baseline)
        diagnostic["aggregate_expected_margin"] = diagnostic["total_horizon_cost_saving"]/diagnostic["total_traded_export_kwh"]
    return windows,diagnostic


def _compact_windows(model,windows,trace,trading=False):
    """Merge actual adjacent commands only after a complete route replay.

    Strict comparisons against the current route prevent spending another
    numerical-tolerance budget. No merge across a manual or passive gap.
    """
    windows=sorted(windows,key=lambda w:w.start)
    _,manual_before=model.simulate({},windows=windows)
    i=0
    attempts=0
    while i+1<len(windows) and attempts<288:
        first,second=windows[i:i+2]
        if (first.end!=second.start or first.action!=second.action or first.origin!=second.origin
                or (second.end-first.start)>timedelta(hours=12)):
            i+=1
            continue
        if trading and first.origin!="trade":
            i+=1
            continue
        attempts+=1
        energy=sum(w.power_kw*(w.end-w.power_start).total_seconds()/3600 for w in (first,second))
        duration=(second.end-first.power_start).total_seconds()/3600
        step=max(10,int((energy/duration*100-1e-9)//1)+1)
        limit=int((model.b.charge_kw if first.action=="charge" else model.b.discharge_kw)*100)
        others=windows[:i]+windows[i+2:]
        merged=replace(first,end=second.end,power_kw=min(step,limit)/100)
        if merged.action=="charge":
            initial=trace[int((merged.start-model.stamps[0]).total_seconds()/900)]["stored_start_kwh"]
            if initial+merged.power_kw*duration*model.b.charge_eff>model.b.capacity+_TOL:
                i+=1
                continue
        trial,manual_trial=model.simulate({},windows=others+[merged],detail=trading)
        safe=all(_need(r,model.b)<=_need(old,model.b)+_EPS for r,old in zip(trial,trace))
        safe &= all((not old["target_reached"] or manual_trial[key]["target_reached"])
                    and (manual_trial[key]["remaining_target_kwh"] or 0)<= (old["remaining_target_kwh"] or 0)+_EPS
                    and (manual_trial[key]["battery_energy_kwh"] >= old["battery_energy_kwh"]-_EPS
                         if next(p.action for p in model.manual if p.id==key)=="discharge" else True)
                    for key,old in manual_before.items())
        if trading:
            safe &= all(sum(s["duration_hours"] for r in trial for s in r["segments"]
                         if s.get("window_id")==w.id and s["action"] in {"safety_charge","trade_charge","trade_discharge"})
                        >=(w.end-w.power_start).total_seconds()/3600-1e-7 for w in others+[merged])
            # Optional exports must keep the complete commanded power phase.
            if merged.action=="discharge":
                endpoint=int((merged.end-model.stamps[0]).total_seconds()/900)-1
                initial=trace[int((merged.start-model.stamps[0]).total_seconds()/900)]["stored_start_kwh"]
                if initial-merged.power_kw*duration/model.b.discharge_eff < model.b.reserve-_EPS:
                    safe=False
            safe &= sum(r["cost"] for r in trial)<=sum(r["cost"] for r in trace)+_EPS
            safe &= all(r["charge_from_solar_kwh"]>=old["charge_from_solar_kwh"]-_EPS for r,old in zip(trial,trace))
            safe &= sum(r["discharge_to_grid_trade_kwh"] for r in trial)>=sum(r["discharge_to_grid_trade_kwh"] for r in trace)-_EPS
            allowed={j for j,t in enumerate(model.stamps) if merged.action=="charge" and merged.start<=t<merged.end}
            safe &= all(j in allowed or r["grid_import_for_home_kwh"]<=old["grid_import_for_home_kwh"]+_EPS for j,(r,old) in enumerate(zip(trial,trace)))
        if safe:
            windows=sorted(others+[merged],key=lambda w:w.start)
            trace,manual_before=trial,manual_trial
        else:
            i+=1
    return windows,trace


def _describe_windows(model,windows,timeline):
    """Serialize the EXACT commands used for the published route, not a replan."""
    result=[]
    for w in windows:
        parts=[s for r in timeline for s in r["segments"] if s.get("window_id")==w.id]
        powered=[s for s in parts if s["action"] in {"safety_charge","trade_charge","trade_discharge"}]
        if not powered:
            continue
        actual_hours=sum(s["duration_hours"] for s in powered)
        requested_hours=(w.end-w.power_start).total_seconds()/3600
        flows={key:sum(s[key] for s in powered) for key in _FLOWS}
        delivered=(sum(flows[f"charge_from_grid_{x}_kwh"] for x in ("safety","trade","manual"))+flows["charge_from_solar_kwh"]
                   if w.action=="charge" else flows["discharge_to_home_kwh"]+flows["discharge_to_grid_kwh"])
        requested=w.power_kw*requested_hours
        shortfall=max(0.,requested-delivered)
        result.append({"id":w.id,"action":w.action,"purpose":w.origin+"_"+w.action,
            "origin":"automatic_72h_planner","start_time":w.start.isoformat(),"power_start_time":w.power_start.isoformat(),
            "planned_end_time":w.end.isoformat(),"preparation_minutes":2,
            "power_w":w.power_kw*1000,"max_runtime_h":(w.end-w.start).total_seconds()/3600,
            "planned_power_duration_h":requested_hours,"projected_power_duration_h":actual_hours,
            "start_soc":parts[0]["stored_start_kwh"]/model.b.capacity*100,
            "target_soc":powered[-1]["stored_end_kwh"]/model.b.capacity*100,
            "command_target_soc":w.target/model.b.capacity*100,
            "projected_end_soc":next(r["soc_end"] for r in timeline if r["end"]==w.end.isoformat()),
            "requested_energy_kwh":requested,"planned_energy_kwh":delivered,
            "energy_shortfall_kwh":shortfall,"flow_energy_basis":"ac","flows":flows,
            "limited":shortfall>_TOL,"reason":"target_or_capacity_limited" if shortfall>_TOL else "complete_window",
            "source_quarters":[r["start"] for r in timeline if any(s.get("window_id")==w.id for s in r["segments"])],
            "observational_only":True,"physical_execution_authority":False})
    for window in result:
        window["planner_identity"] = window["id"]
        window["planner_signature"] = sha256(json.dumps(window,sort_keys=True,
            separators=(",",":"),allow_nan=False).encode()).hexdigest()
    return result


def calculate_plan72(home_slots, solar_slots, price_slots, *, now, soc_percent,
                     capacity_kwh, min_soc_percent, reserve_percent,
                     charge_efficiency=0.92, discharge_efficiency=0.92,
                     max_charge_power_w, max_discharge_power_w,
                     minimum_trade_margin=0.10, trade_enabled=True, manual_plans=(), practical_windows=False):
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
        if (not isinstance(practical_windows, bool) or not 0 <= soc <= 100 or capacity <= 0 or not 0 <= minimum < 100
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
    windows = []
    window_search = {}
    if practical_windows:
        windows, baseline, window_search = _safety_windows(model)
        windows, trade = _trade_windows(model, windows, baseline, margin, trade_enabled)
        timeline, manual_progress = model.simulate({}, windows=windows, detail=True)
    else:
        # Retained pure Alpha52 API for numeric regression/oracle comparisons.
        # The HA runtime explicitly selects the practical window contract.
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
    window_details = _describe_windows(model, windows, timeline) if practical_windows else []
    window_limited = any(w["limited"] for w in window_details) or window_search.get("search_limited", False)
    limited = reserve_breaches > 0 or physical_shortfall or manual_limited or window_limited
    reason = ("remaining_physical_shortfall" if physical_shortfall else
              "manual_plan_limited" if manual_limited else
              "reserve_breach_in_projection" if reserve_breaches else
              "action_window_limited" if window_limited else "sequential_plan_ready")
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
        "action_windows": window_details, "action_window_count": len(window_details),
        "action_window_contract": "quarter_windows_v1" if practical_windows else "legacy_segments",
        "action_window_search": window_search,
        "projection_count": model.calls,
        "model": "deterministic_segmented_self_consumption",
        "globally_optimal": False,
    }
