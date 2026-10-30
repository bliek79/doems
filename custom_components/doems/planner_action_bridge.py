"""Observer-only adapter for the exact Plan72 quarter_windows_v1 commands.

No route simulation, optimization, slot storage or execution takes place here.
All energies are AC kWh unless explicitly stored battery energy.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any

CONTRACT_VERSION = "doems_action_bridge_v1"
SOURCE_CONTRACT = "quarter_windows_v1"
SLOT_CAPACITY = 3
_EPS = 1e-8
_ENERGY_TOL = 1e-5  # Preserve Plan72's numerical tolerance; never round shortages away.
_TYPES = {"safety_charge": "safety_charge", "trade_charge": "trade_charge",
          "trade_discharge": "grid_discharge"}
_FLOWS = ("charge_from_solar_kwh", "charge_from_grid_safety_kwh",
          "charge_from_grid_trade_kwh", "charge_from_grid_manual_kwh",
          "discharge_to_home_kwh", "discharge_to_grid_kwh",
          "discharge_to_grid_trade_kwh", "discharge_to_grid_manual_kwh",
          "grid_import_for_home_kwh", "solar_export_kwh", "solar_to_home_kwh", "losses_kwh")


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


def _equal(a: Any, b: Any, reason: str, tolerance: float = _ENERGY_TOL) -> None:
    if abs(_number(a) - _number(b)) > tolerance:
        raise ValueError(reason)


def _base(plan: dict) -> dict:
    return {"contract_version": CONTRACT_VERSION, "source_contract": plan.get("action_window_contract"),
            "status": "invalid", "valid": False, "reason": "invalid_plan72",
            "observational_only": True, "execution_enabled": False,
            "physical_execution_authority": False, "plan_store_write_enabled": False,
            "scheduler_handoff_enabled": False, "slot_capacity": SLOT_CAPACITY,
            "source_plan_generation": plan.get("plan_generation"),
            "source_input_fingerprint": plan.get("input_fingerprint"),
            "source_calculated_at": plan.get("calculated_at"),
            "source_status": plan.get("status"), "source_reason": plan.get("reason"),
            "candidates": [], "eligible_candidates": [], "slot_preview": [], "overflow_candidates": [],
            "candidate_count": 0, "invalid_candidate_count": 0, "held_after_invalid_count": 0,
            "capacity_limited_count": 0, "energy_shortfall_kwh": 0.0,
            "energy_shortfall_basis": "total_battery_ac_energy",
            "preview_semantics": "first_three_eligible_candidates_assuming_free_capacity"}


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


def _source(plan: dict, now: datetime) -> tuple[list[dict], dict]:
    """Validate structural coverage and index exact segments; do not replan."""
    if plan.get("action_window_contract") != SOURCE_CONTRACT:
        raise ValueError("unsupported_action_window_contract")
    generation = plan.get("plan_generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise ValueError("missing_plan_generation")
    if not isinstance(plan.get("input_fingerprint"), str) or not plan["input_fingerprint"]:
        raise ValueError("missing_input_fingerprint")
    calculated = _time(plan.get("calculated_at"))
    if calculated > now:
        raise ValueError("future_calculation")
    start, end = _time(plan.get("start")), _time(plan.get("end"))
    floor = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
    next_quarter = floor if floor == now else floor + timedelta(minutes=15)
    if start != next_quarter:
        raise ValueError("stale_or_future_plan72_window")
    if end-start != timedelta(hours=72) or calculated < start-timedelta(minutes=15):
        raise ValueError("invalid_horizon_or_calculation_age")
    timeline, windows = plan.get("timeline"), plan.get("action_windows")
    if (not isinstance(timeline, list) or len(timeline) != 288
            or plan.get("slot_count") != 288 or plan.get("horizon_hours") != 72):
        raise ValueError("invalid_288_quarter_timeline")
    if not isinstance(windows, list) or plan.get("action_window_count") != len(windows):
        raise ValueError("invalid_action_window_count")
    ids = [w.get("id") for w in windows]
    if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError("invalid_or_duplicate_window_identity")
    by_id = {key: [] for key in ids}
    for index, row in enumerate(timeline):
        begin = start + timedelta(minutes=15*index)
        finish = begin + timedelta(minutes=15)
        if _time(row.get("start")) != begin or _time(row.get("end")) != finish:
            raise ValueError("noncontiguous_quarter_timeline")
        segments = row.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ValueError("missing_segments")
        cursor = begin
        for j, segment in enumerate(segments):
            s, e = _time(segment.get("start")), _time(segment.get("end"))
            if s != cursor or not s < e <= finish:
                raise ValueError("noncontiguous_segment_timeline")
            _equal(segment.get("duration_hours"), (e-s).total_seconds()/3600,
                   "segment_duration_mismatch", _EPS)
            cursor = e
            key = segment.get("window_id")
            if key is not None:
                if key not in by_id:
                    raise ValueError("unknown_source_window")
                by_id[key].append((row, j, segment))
            elif segment.get("action") in _TYPES and segment.get("manual_id") is None:
                raise ValueError("explicit_segment_without_window")
        if cursor != finish:
            raise ValueError("incomplete_segment_quarter")
    return sorted(windows, key=lambda w: _time(w.get("start_time"))), by_id


def _candidate(w: dict, parts: list, p: dict, source: dict, horizon: tuple,
               previous_end: datetime | None, timeline: list) -> dict:
    # Source identity is retained verbatim. The Bridge identity follows Alpha84's
    # purpose + source anchors + end rule, independent of SOC/power revisions.
    c = deepcopy(w)
    c.update(action_type=_TYPES.get(w.get("purpose")), execution_mode="scheduled",
             source_window_id=w.get("id"), source_planner_identity=w.get("planner_identity"),
             source_planner_signature=w.get("planner_signature"),
             valid=False, validation_reasons=[], validation_warnings=[], capacity_limited=False,
             observational_only=True, execution_enabled=False, physical_execution_authority=False,
             **source)
    try:
        charge = w.get("action") == "charge"
        purpose = w.get("purpose")
        if purpose not in _TYPES or w.get("action") != ("discharge" if purpose == "trade_discharge" else "charge"):
            raise ValueError("invalid_action_purpose")
        if w.get("origin") != "automatic_72h_planner" or w.get("flow_energy_basis") != "ac":
            raise ValueError("invalid_action_origin_or_energy_basis")
        if w.get("physical_execution_authority") is not False or w.get("observational_only") is not True:
            raise ValueError("source_execution_authority_mismatch")
        signature_payload = {k: v for k, v in w.items() if k != "planner_signature"}
        if w.get("planner_identity") != w["id"] or w.get("planner_signature") != _hash(signature_payload):
            raise ValueError("source_window_signature_mismatch")
        start, power_start, end = (_time(w.get(key)) for key in ("start_time", "power_start_time", "planned_end_time"))
        c.update(start_time=start.isoformat(), power_start_time=power_start.isoformat(), planned_end_time=end.isoformat())
        if (not horizon[0] <= start < power_start < end <= horizon[1]
                or any(t.minute % 15 or t.second or t.microsecond for t in (start, end))
                or previous_end is not None and start < previous_end):
            raise ValueError("invalid_or_overlapping_window")
        hours = (end-start).total_seconds()/3600
        if not .25 <= hours <= 12:
            raise ValueError("invalid_window_duration")
        _equal(w.get("max_runtime_h"), hours, "runtime_mismatch", _EPS)
        _equal(w.get("preparation_minutes"), 2, "preparation_mismatch", _EPS)
        _equal((power_start-start).total_seconds(), 120, "preparation_mismatch", _EPS)
        usable = (end-power_start).total_seconds()/3600
        _equal(w.get("planned_power_duration_h"), usable, "power_duration_mismatch", _EPS)
        power = _number(w.get("power_w"))
        limit = p["max_charge_power_w" if charge else "max_discharge_power_w"]
        if not 100 <= power <= limit+_EPS or abs(power/10-round(power/10)) > _EPS:
            raise ValueError("invalid_power")
        cap = p["capacity_kwh"]
        eta = p["charge_efficiency" if charge else "discharge_efficiency"]
        floor = cap*p["min_soc_percent"]/100
        reserve = cap*(p["min_soc_percent"]+p["reserve_percent"])/100
        if not parts:
            raise ValueError("missing_window_segments")
        origin = "safety" if purpose == "safety_charge" else "trade"
        expected_action = "trade_discharge" if not charge else purpose
        flows = {key: 0.0 for key in _FLOWS}
        prepared, powered = 0.0, 0.0
        cursor, stored = start, _number(parts[0][2].get("stored_start_kwh"))
        initial = stored
        refs, quarters = [], []
        for row, j, s in parts:
            begin, finish = _time(s["start"]), _time(s["end"])
            if begin != cursor or not start <= begin < finish <= end:
                raise ValueError("noncontiguous_window_segments")
            cursor = finish
            if s.get("origin") != origin or s.get("manual_id") is not None:
                raise ValueError("window_segment_origin_mismatch")
            before, after = _number(s.get("stored_start_kwh")), _number(s.get("stored_end_kwh"))
            _equal(before, stored, "source_soc_discontinuity")
            if min(before, after) < floor-_ENERGY_TOL or max(before, after) > cap+_ENERGY_TOL:
                raise ValueError("source_soc_out_of_bounds")
            values = {key: _number(s.get(key)) for key in _FLOWS}
            if any(v < 0 for v in values.values()):
                raise ValueError("negative_segment_energy")
            incoming = sum(values[key] for key in _FLOWS[:4])
            outgoing = values["discharge_to_home_kwh"]+values["discharge_to_grid_kwh"]
            duration = _number(s["duration_hours"])
            if begin < power_start:
                if finish > power_start or s.get("action") != origin+"_preparation":
                    raise ValueError("invalid_preparation_segment")
                _equal(s.get("battery_power_w"), 0, "preparation_not_zero", _EPS)
                _equal(incoming+outgoing, 0, "preparation_battery_energy", _EPS)
                _equal(after, before, "preparation_soc_changed")
                prepared += duration
            else:
                if s.get("action") != expected_action:
                    raise ValueError("invalid_powered_segment")
                signed_power = power if charge else -power
                _equal(s.get("battery_power_w"), signed_power, "segment_power_mismatch", 1e-5)
                energy = incoming if charge else outgoing
                _equal(energy, power*duration/1000, "segment_power_energy_mismatch")
                _equal(outgoing if charge else incoming, 0, "contradictory_energy_direction", _EPS)
                _equal(after-before, energy*eta if charge else -energy/eta, "segment_soc_energy_mismatch")
                _equal(s.get("target_soc"), w.get("command_target_soc"), "command_target_mismatch")
                if (values["charge_from_grid_manual_kwh"] > _EPS
                        or values["discharge_to_grid_manual_kwh"] > _EPS):
                    raise ValueError("manual_energy_in_automatic_action")
                _equal(values["discharge_to_grid_kwh"], values["discharge_to_grid_trade_kwh"], "grid_export_origin_mismatch")
                if charge:
                    other = "trade" if origin == "safety" else "safety"
                    _equal(values["charge_from_grid_"+other+"_kwh"], 0, "charge_origin_mismatch", _EPS)
                elif values["discharge_to_grid_kwh"] > _EPS:
                    if after < reserve-_ENERGY_TOL or _number(row.get("export_all_in")) < 0:
                        raise ValueError("unsafe_trade_discharge")
                for key in _FLOWS:
                    flows[key] += values[key]
                powered += duration
            stored = after
            quarter = _time(row["start"]).isoformat()
            if quarter not in quarters:
                quarters.append(quarter)
            refs.append({"quarter_start": quarter, "segment_index": j,
                         "start": begin.isoformat(), "end": finish.isoformat()})
        _equal(prepared, 2/60, "preparation_duration_mismatch", _EPS)
        if powered <= _EPS or powered > usable+_EPS:
            raise ValueError("invalid_projected_power_duration")
        if [_time(q).isoformat() for q in w.get("source_quarters", [])] != quarters:
            raise ValueError("source_quarters_mismatch")
        _equal(w.get("projected_power_duration_h"), powered, "projected_duration_mismatch", _EPS)
        _equal(w.get("start_soc"), initial/cap*100, "start_soc_mismatch")
        _equal(w.get("target_soc"), stored/cap*100, "target_soc_mismatch")
        command_target = _number(w.get("command_target_soc"))
        if not p["min_soc_percent"] <= command_target <= 100:
            raise ValueError("invalid_command_target_soc")
        # Verify the public executable target without changing the route.
        if charge and stored > command_target/100*cap+_ENERGY_TOL or not charge and stored < command_target/100*cap-_ENERGY_TOL:
            raise ValueError("target_beyond_command_bound")
        for key in _FLOWS:
            _equal(w.get("flows", {}).get(key), flows[key], "window_flow_mismatch")
        delivered = sum(flows[k] for k in _FLOWS[:4]) if charge else flows["discharge_to_home_kwh"]+flows["discharge_to_grid_kwh"]
        if any(_number(w.get(key)) < 0 for key in (
                "requested_energy_kwh", "planned_energy_kwh", "energy_shortfall_kwh")):
            raise ValueError("negative_window_energy")
        requested = power*usable/1000
        shortfall = max(0., requested-delivered)
        _equal(w.get("requested_energy_kwh"), requested, "requested_energy_mismatch")
        _equal(w.get("planned_energy_kwh"), delivered, "planned_energy_mismatch")
        _equal(w.get("energy_shortfall_kwh"), shortfall, "energy_shortfall_mismatch")
        if delivered <= _EPS:
            raise ValueError("no_action_energy")
        explicit = flows["charge_from_grid_"+origin+"_kwh"] if charge else flows["discharge_to_grid_trade_kwh"]
        if explicit <= _EPS:
            raise ValueError("no_explicit_grid_energy")
        if not isinstance(w.get("limited"), bool) or w["limited"] != (shortfall > _ENERGY_TOL):
            raise ValueError("window_limitation_mismatch")
        if not charge and w["limited"]:
            raise ValueError("limited_discharge_requires_replanning")
        expected_reason = "target_or_capacity_limited" if w["limited"] else "complete_window"
        if w.get("reason") != expected_reason:
            raise ValueError("window_reason_mismatch")
        end_row = next(r for r in timeline if _time(r["end"]) == end)
        _equal(w.get("projected_end_soc"), end_row.get("soc_end"), "projected_end_soc_mismatch")
        c.update(valid=True, source_segments=refs, source_quarters=quarters,
                 capacity_limited=w["limited"], feasible_energy_kwh=delivered,
                 explicit_grid_energy_kwh=explicit, power_limit_w=limit,
                 battery_parameters=deepcopy(p), projected_start_soc=w["start_soc"],
                 flow_energy_basis="ac")
        if w["limited"]:
            c["validation_warnings"].append("partial_charge_from_plan72_window")
    except (ValueError, TypeError, OverflowError, KeyError, AttributeError) as error:
        c["validation_reasons"].append(str(error) or "invalid_candidate")
    # A malformed source candidate remains individually visible with its source
    # ID, even when no well-formed stable identity can be calculated.
    try:
        c["planner_identity"] = _hash({"contract": CONTRACT_VERSION, "purpose": w.get("purpose"),
            "source_quarters": [_time(q).isoformat() for q in w.get("source_quarters", [])],
            "planned_end_time": _time(w.get("planned_end_time")).isoformat()})
        payload = {k: v for k, v in c.items() if k not in source and k not in {
            "planner_identity", "planner_signature", "id", "source_window_id",
            "source_planner_identity", "source_planner_signature"}}
        c["planner_signature"] = _hash(payload)
    except (ValueError, TypeError, OverflowError):
        c.update(valid=False, planner_identity=str(w.get("id")), planner_signature=None)
        c["validation_reasons"].append("nonserializable_candidate")
    # Keep diagnostics JSON-safe even for malformed nonfinite source values.
    def safe(value):
        if isinstance(value, float) and not isfinite(value):
            return None
        if isinstance(value, dict):
            return {k: safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [safe(v) for v in value]
        return value
    return safe(c)


def build_action_bridge(plan: dict, *, now: datetime) -> dict:
    """Expose the valid chronological prefix and a nonpersistent three-item preview."""
    result = _base(plan)
    if plan.get("valid") is not True or plan.get("status") not in {"ready", "limited"}:
        result["reason"] = "plan72_"+str(plan.get("reason", "unavailable"))
        return result
    try:
        now = _time(now)
        p = _parameters(plan.get("battery_parameters"))
        windows, by_id = _source(plan, now)
    except (ValueError, TypeError, OverflowError, KeyError, AttributeError) as error:
        result["reason"] = str(error) or "invalid_plan72_contract"
        return result
    source = {key: result[key] for key in ("source_plan_generation", "source_input_fingerprint", "source_calculated_at")}
    candidates, previous_end = [], None
    for w in windows:
        c = _candidate(w, by_id[w["id"]], p, source,
                       (_time(plan["start"]), _time(plan["end"])), previous_end, plan["timeline"])
        try:
            end = _time(w["planned_end_time"])
            previous_end = max(previous_end, end) if previous_end else end
        except (ValueError, TypeError, KeyError):
            pass  # Individually invalid window already stops chronological selection.
        candidates.append(c)
    blocked_by, limited_before, eligible = None, False, []
    recovery = plan.get("status") == "limited" or plan.get("reserve_satisfied") is not True
    for index, c in enumerate(candidates):
        c.update(candidate_index=index, depends_on_limited_projection=limited_before)
        if blocked_by is not None:
            c.update(selection_status="held_after_invalid", blocked_by_identity=blocked_by)
        elif not c["valid"]:
            blocked_by = c["planner_identity"]
            c["selection_status"] = "invalid"
        elif recovery and c["action_type"] != "safety_charge":
            c["selection_status"] = "held_source_route_limited"
        else:
            c["selection_status"] = "eligible"
            eligible.append(c)
        limited_before |= c["capacity_limited"]
    invalid = sum(not c["valid"] for c in candidates)
    result.update(candidates=candidates, eligible_candidates=eligible,
        slot_preview=eligible[:SLOT_CAPACITY], overflow_candidates=eligible[SLOT_CAPACITY:],
        candidate_count=len(candidates), invalid_candidate_count=invalid,
        held_after_invalid_count=sum(c["selection_status"] == "held_after_invalid" for c in candidates),
        capacity_limited_count=sum(c["capacity_limited"] for c in candidates),
        energy_shortfall_kwh=sum(_number(c["energy_shortfall_kwh"]) for c in candidates if c["valid"]))
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
