"""Observer-only Plan72 translation. No forecast, SOC route, storage or I/O.

Energy is AC kWh except stored_* (battery kWh). Candidates retain exact source
segments. Alpha84's chronological prefix and partial-charge rule are preserved.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any

CONTRACT_VERSION = "doems_action_bridge_v1"
HANDOFF_ALLOWANCE_MIN = 2.0
SLOT_CAPACITY = 3
_EPS = 1e-9
_ENERGY_TOL = 1e-5  # Same battery-kWh numerical tolerance as Plan72.
_TYPES = {"safety_charge": "safety_charge", "trade_charge": "trade_charge",
          "trade_discharge": "grid_discharge"}
_FLOWS = ("charge_from_solar_kwh", "charge_from_grid_safety_kwh",
          "charge_from_grid_trade_kwh", "charge_from_grid_manual_kwh",
          "discharge_to_home_kwh", "discharge_to_grid_kwh",
          "discharge_to_grid_trade_kwh", "discharge_to_grid_manual_kwh")


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean_number")
    number = float(value)
    if not isfinite(number):
        raise ValueError("nonfinite_number")
    return number


def _time(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("invalid_timestamp")
    return value.astimezone(timezone.utc)


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def _base(plan: dict) -> dict:
    return {"contract_version": CONTRACT_VERSION, "status": "invalid", "valid": False,
            "reason": "invalid_plan72", "observational_only": True,
            "execution_enabled": False, "physical_execution_authority": False,
            "plan_store_write_enabled": False, "scheduler_handoff_enabled": False,
            "source_plan_generation": plan.get("plan_generation"),
            "source_input_fingerprint": plan.get("input_fingerprint"),
            "source_calculated_at": plan.get("calculated_at"),
            "source_status": plan.get("status"), "source_reason": plan.get("reason"),
            "slot_capacity": SLOT_CAPACITY, "candidates": [], "eligible_candidates": [],
            "slot_preview": [], "overflow_candidates": [], "candidate_count": 0,
            "invalid_candidate_count": 0, "held_after_invalid_count": 0,
            "capacity_limited_count": 0, "energy_shortfall_kwh": 0.0,
            "energy_shortfall_basis": "total_battery_ac_energy",
            "projection_revalidation_required": False}


def _parameters(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("missing_battery_parameters")
    keys = ("capacity_kwh", "min_soc_percent", "reserve_percent", "charge_efficiency",
            "discharge_efficiency", "max_charge_power_w", "max_discharge_power_w")
    p = {key: _number(raw.get(key)) for key in keys}
    if (p["capacity_kwh"] <= 0 or not 0 <= p["min_soc_percent"] < 100
            or not 0 <= p["reserve_percent"] <= 100 - p["min_soc_percent"]
            or not 0 < p["charge_efficiency"] <= 1 or not 0 < p["discharge_efficiency"] <= 1
            or p["max_charge_power_w"] <= 0 or p["max_discharge_power_w"] <= 0):
        raise ValueError("invalid_battery_parameters")
    return p


def _windows(plan: dict, now: datetime) -> list[list[dict]]:
    """Validate native temporal coverage; never bridge a passive gap."""
    start, end = _time(plan.get("start")), _time(plan.get("end"))
    if start.minute % 15 or start.second or start.microsecond or end - start != timedelta(hours=72):
        raise ValueError("invalid_horizon")
    floor = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
    next_quarter = floor if floor == now else floor + timedelta(minutes=15)
    if start != next_quarter:
        raise ValueError("stale_or_future_plan72_window")
    timeline = plan.get("timeline")
    if not isinstance(timeline, list) or len(timeline) != 288 or plan.get("slot_count") != 288 or plan.get("horizon_hours") != 72:
        raise ValueError("invalid_288_quarter_timeline")
    windows: list[list[dict]] = []
    for index, row in enumerate(timeline):
        begin = start + timedelta(minutes=15 * index)
        finish = begin + timedelta(minutes=15)
        if _time(row.get("start")) != begin or _time(row.get("end")) != finish:
            raise ValueError("noncontiguous_quarter_timeline")
        cursor = begin
        segments = row.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ValueError("missing_segments")
        for segment_index, raw in enumerate(segments):
            s, e = _time(raw.get("start")), _time(raw.get("end"))
            if s != cursor or not s < e <= finish:
                raise ValueError("noncontiguous_segment_timeline")
            if abs(_number(raw.get("duration_hours")) - (e-s).total_seconds()/3600) > _EPS:
                raise ValueError("segment_duration_mismatch")
            cursor = e
            action_type = _TYPES.get(raw.get("action"))
            if action_type is None or raw.get("origin") not in {"safety", "trade"} or raw.get("manual_id") is not None:
                continue
            # A trade discharge without grid export is home coverage, not an
            # explicit export candidate. Nonfinite values are validated below.
            if action_type == "grid_discharge" and raw.get("discharge_to_grid_trade_kwh") == 0:
                continue
            item = deepcopy(raw)
            item.update(action_type=action_type, quarter_start=begin.isoformat(),
                        source_segment_index=segment_index,
                        import_all_in=row.get("import_all_in"), export_all_in=row.get("export_all_in"),
                        price_kind=row.get("kind"), source_resolution_minutes=row.get("source_resolution_minutes"))
            previous = windows[-1][-1] if windows else None
            if (previous and _time(previous["end"]) == s
                    and previous["action_type"] == action_type
                    and previous.get("battery_power_w") == item.get("battery_power_w")
                    and previous.get("target_soc") == item.get("target_soc")):
                windows[-1].append(item)
            else:
                windows.append([item])
        if cursor != finish:
            raise ValueError("incomplete_segment_quarter")
    return windows


def _candidate(parts: list[dict], p: dict, source: dict) -> dict:
    first, last = parts[0], parts[-1]
    kind = first["action_type"]
    charge = kind != "grid_discharge"
    start, end = _time(first["start"]), _time(last["end"])
    duration = (end - start).total_seconds() / 3600
    refs = [{"quarter_start": x["quarter_start"], "segment_index": x["source_segment_index"],
             "start": x["start"], "end": x["end"]} for x in parts]
    # Nominal quarter anchors remain stable across SOC/energy revisions. A
    # changed set of source quarters deliberately creates a different identity.
    identity = _hash({"contract": CONTRACT_VERSION, "action_type": kind,
                      "source_quarters": sorted({x["quarter_start"] for x in parts}),
                      "window_start": start.isoformat()})
    result = {"action": "charge" if charge else "discharge", "action_type": kind,
              "purpose": kind, "origin": "automatic_72h_planner", "execution_mode": "scheduled",
              "start_time": start.isoformat(), "planned_end_time": end.isoformat(),
              "max_runtime_h": duration, "handoff_allowance_min": HANDOFF_ALLOWANCE_MIN,
              "source_segments": refs, "source_segment_data": deepcopy(parts),
              "planner_identity": identity, "valid": False, "validation_reasons": [],
              "validation_warnings": [], "capacity_limited": False,
              "requested_energy_kwh": None, "planned_energy_kwh": None,
              "energy_shortfall_kwh": None, "target_soc": None,
              "observational_only": True, "execution_enabled": False,
              "physical_execution_authority": False, **source}
    try:
        limit = p["max_charge_power_w" if charge else "max_discharge_power_w"]
        power = _number(first.get("battery_power_w"))
        if (charge and power <= 0) or (not charge and power >= 0) or abs(power) > limit + _EPS:
            raise ValueError("invalid_power")
        power = abs(power)
        cap, eta = p["capacity_kwh"], p["charge_efficiency" if charge else "discharge_efficiency"]
        energies = {flow: 0.0 for flow in _FLOWS}
        stored_before = _number(first.get("stored_start_kwh"))
        cursor = stored_before
        floor = cap * p["min_soc_percent"] / 100
        reserve = cap * (p["min_soc_percent"] + p["reserve_percent"]) / 100
        for part in parts:
            if part.get("origin") != ("safety" if kind == "safety_charge" else "trade"):
                raise ValueError("action_origin_mismatch")
            before, after = _number(part.get("stored_start_kwh")), _number(part.get("stored_end_kwh"))
            if abs(before - cursor) > _ENERGY_TOL:
                raise ValueError("source_soc_discontinuity")
            if min(before, after) < floor - _ENERGY_TOL or max(before, after) > cap + _ENERGY_TOL:
                raise ValueError("source_soc_out_of_bounds")
            values = {flow: _number(part.get(flow)) for flow in _FLOWS}
            if any(value < 0 for value in values.values()):
                raise ValueError("negative_segment_energy")
            input_energy = sum(values[x] for x in _FLOWS[:4])
            output_energy = values["discharge_to_home_kwh"] + values["discharge_to_grid_kwh"]
            commanded = input_energy if charge else output_energy
            hours = _number(part["duration_hours"])
            if abs(commanded - power * hours / 1000) > _ENERGY_TOL:
                raise ValueError("segment_power_energy_mismatch")
            if (charge and output_energy > _EPS) or (not charge and input_energy > _EPS):
                raise ValueError("contradictory_energy_direction")
            if values["charge_from_grid_manual_kwh"] > _EPS or values["discharge_to_grid_manual_kwh"] > _EPS:
                raise ValueError("manual_energy_in_automatic_action")
            if abs(values["discharge_to_grid_kwh"] - values["discharge_to_grid_trade_kwh"]) > _ENERGY_TOL:
                raise ValueError("grid_export_origin_mismatch")
            if kind == "safety_charge" and values["charge_from_grid_trade_kwh"] > _EPS:
                raise ValueError("charge_origin_mismatch")
            if kind == "trade_charge" and values["charge_from_grid_safety_kwh"] > _EPS:
                raise ValueError("charge_origin_mismatch")
            if kind == "grid_discharge" and (after < reserve - _ENERGY_TOL or _number(part.get("export_all_in")) < 0):
                raise ValueError("unsafe_trade_discharge")
            delta = commanded * eta if charge else -commanded / eta
            if abs(after - before - delta) > _ENERGY_TOL:
                raise ValueError("segment_soc_energy_mismatch")
            target = _number(part.get("target_soc"))
            if not p["min_soc_percent"] <= target <= 100:
                raise ValueError("invalid_plan72_target_soc")
            for flow in _FLOWS:
                energies[flow] += values[flow]
            cursor = after
        requested = power * duration / 1000
        if requested <= _EPS:
            raise ValueError("no_action_energy")
        usable = max(0.0, duration - HANDOFF_ALLOWANCE_MIN / 60)
        feasible = power * usable / 1000
        result.update(power_w=power, power_limit_w=limit,
                      requested_energy_kwh=requested, planned_energy_kwh=feasible,
                      feasible_energy_kwh=feasible, energy_shortfall_kwh=requested-feasible,
                      requested_flows=energies, projected_start_soc=stored_before/cap*100,
                      projected_end_soc=cursor/cap*100, plan72_target_soc=last["target_soc"],
                      power_window_start=(start+timedelta(minutes=HANDOFF_ALLOWANCE_MIN)).isoformat())
        if usable <= _EPS or feasible <= _EPS:
            raise ValueError("no_usable_window_after_handoff")
        # Alpha84 permits capped CHARGE only. An export whose exact source
        # energy cannot fit remains invalid; it is never silently extrapolated.
        if not charge and requested - feasible > _ENERGY_TOL * eta:
            raise ValueError("discharge_energy_does_not_fit_handoff_window")
        # Attribute the retained energy to the exact suffix of source segments,
        # rather than scaling a mixed PV/grid window as if it were uniform.
        retained = {flow: 0.0 for flow in _FLOWS}
        power_start = start + timedelta(minutes=HANDOFF_ALLOWANCE_MIN)
        for part in parts:
            s, e = _time(part["start"]), _time(part["end"])
            ratio = max(0.0, (e-max(s, power_start)).total_seconds()) / (e-s).total_seconds()
            for flow in _FLOWS:
                retained[flow] += _number(part[flow]) * ratio
        target = (stored_before + feasible*eta if charge else stored_before-feasible/eta) / cap*100
        if target < p["min_soc_percent"] - _EPS or target > 100 + _EPS:
            raise ValueError("invalid_feasible_target_soc")
        result.update(valid=True, target_soc=target, planned_flows=retained,
                      capacity_limited=requested-feasible > _ENERGY_TOL / eta,
                      energy_shortfall_by_flow={key: energies[key]-retained[key] for key in _FLOWS},
                      battery_parameters=deepcopy(p), projection_revalidation_required=requested > feasible + _EPS)
        if result["capacity_limited"]:
            result["validation_warnings"].append("partial_charge_due_to_handoff_window")
    except (ValueError, TypeError, OverflowError, KeyError) as error:
        result["validation_reasons"].append(str(error) or "invalid_candidate")
    # Full precision; generation is provenance, not an actionable revision.
    payload = {key: value for key, value in result.items() if key not in source}
    try:
        result["planner_signature"] = _hash(payload)
    except (ValueError, TypeError):
        result["valid"] = False
        result["validation_reasons"].append("nonserializable_candidate")
        result["planner_signature"] = None
    return result


def build_action_bridge(plan: dict, *, now: datetime) -> dict:
    """Return all candidates plus a chronological prefix and three-item preview."""
    result = _base(plan)
    if plan.get("valid") is not True or plan.get("status") not in {"ready", "limited"}:
        result["reason"] = "plan72_" + str(plan.get("reason", "unavailable"))
        return result
    try:
        now = _time(now)
        p = _parameters(plan.get("battery_parameters"))
        if not isinstance(plan.get("plan_generation"), int) or isinstance(plan.get("plan_generation"), bool):
            raise ValueError("missing_plan_generation")
        if not isinstance(plan.get("input_fingerprint"), str) or not plan["input_fingerprint"]:
            raise ValueError("missing_input_fingerprint")
        _time(plan.get("calculated_at"))
        windows = _windows(plan, now)
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError) as error:
        result["reason"] = str(error) or "invalid_plan72_contract"
        return result
    source = {key: result[key] for key in ("source_plan_generation", "source_input_fingerprint", "source_calculated_at")}
    candidates = [_candidate(parts, p, source) for parts in windows]
    eligible = []
    blocked_by = None
    # A limited source route can expose recovery charges without promoting
    # trade that relies on an unsatisfied reserve/physical-shortfall route.
    recovery = not plan.get("reserve_satisfied") or plan.get("status") == "limited"
    limited_before = False
    for index, candidate in enumerate(candidates):
        candidate["candidate_index"] = index
        candidate["depends_on_limited_projection"] = limited_before
        if blocked_by is not None:
            candidate.update(selection_status="held_after_invalid", blocked_by_identity=blocked_by)
        elif not candidate["valid"]:
            blocked_by = candidate["planner_identity"]
            candidate["selection_status"] = "invalid"
        elif recovery and candidate["action_type"] != "safety_charge":
            candidate["selection_status"] = "held_source_route_limited"
        else:
            candidate["selection_status"] = "eligible"
            eligible.append(candidate)
        limited_before |= bool(candidate.get("capacity_limited"))
    invalid = sum(not item["valid"] for item in candidates)
    result.update(candidates=candidates, eligible_candidates=eligible,
                  slot_preview=eligible[:SLOT_CAPACITY], overflow_candidates=eligible[SLOT_CAPACITY:],
                  candidate_count=len(candidates), invalid_candidate_count=invalid,
                  held_after_invalid_count=sum(x["selection_status"] == "held_after_invalid" for x in candidates),
                  capacity_limited_count=sum(bool(x["capacity_limited"]) for x in candidates),
                  energy_shortfall_kwh=sum(x.get("energy_shortfall_kwh") or 0 for x in candidates),
                  projection_revalidation_required=any(x.get("projection_revalidation_required") for x in candidates))
    if not candidates:
        result.update(valid=True, status="idle", reason="no_explicit_automatic_actions")
    elif not eligible:
        result.update(status="blocked", reason="first_candidate_invalid" if invalid else "source_route_restricts_trade")
    else:
        limited = recovery or invalid or result["capacity_limited_count"]
        result.update(valid=True, status="limited" if limited else "ready",
                      reason="chronological_prefix_before_invalid" if invalid else
                      "bounded_charge_candidates" if result["capacity_limited_count"] else
                      "safety_recovery_candidates" if recovery else "action_candidates_ready")
    return result
