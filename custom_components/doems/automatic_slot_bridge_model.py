"""R6: map completed R5 native quarter decisions to three slot *proposals*.

This module is pure.  It neither edits R5 planner results nor starts a scheduler,
safety gate or battery service.  Ordinary PV charging and home discharge stay
under the battery's normal self-consumption mode.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any, Mapping

RESOLUTION = timedelta(minutes=15)
AUTO_ORIGIN = "automatic_72h_planner"
START_DELAY_MIN = 10.0
MIN_POWER_W = 100.0
MAX_AUTO_DURATION_H = 12.0
EPS = 1e-7


def _finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite")
    return result


def _utc(value: Any) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError("timestamp_without_timezone")
    return result.astimezone(timezone.utc)


def _extract(row: Mapping[str, Any]) -> tuple[str, str, float] | None:
    safety = _finite(row.get("charge_from_grid_safety_kwh") or 0.0)
    trading = _finite(row.get("charge_from_grid_trade_kwh") or 0.0)
    export = _finite(row.get("trade_discharge_to_grid_kwh") or 0.0)
    if min(safety, trading, export) < -EPS:
        raise ValueError("negative_explicit_grid_energy")
    if export > EPS and (safety > EPS or trading > EPS):
        raise ValueError("simultaneous_charge_and_discharge")
    if export > EPS:
        return "ontladen", "handel_ontladen", export
    if safety > EPS or trading > EPS:
        if safety > EPS and trading > EPS:
            purpose = "veiligheidsladen+handelsladen"
        elif safety > EPS:
            purpose = "veiligheidsladen"
        else:
            purpose = "handelsladen"
        return "laden", purpose, safety + trading
    return None


def _segment_to_proposal(
    segment: list[dict[str, Any]],
    *,
    capacity_kwh: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    max_charge_power_w: float,
    max_discharge_power_w: float,
) -> tuple[dict[str, Any] | None, str | None]:
    first, last = segment[0], segment[-1]
    start: datetime = first["_start"]
    end: datetime = last["_end"]
    duration_h = (end - start).total_seconds() / 3600.0
    if not 0.25 <= duration_h <= MAX_AUTO_DURATION_H:
        return None, "automatic_duration_unrepresentable"
    energy = sum(float(item["_energy"]) for item in segment)
    if energy <= EPS:
        return None, "automatic_energy_zero"
    action, purpose = str(first["_action"]), str(first["_purpose"])
    limit = max_charge_power_w if action == "laden" else max_discharge_power_w
    average_power = energy * 1000.0 / duration_h
    requested_energy = energy
    # Alpha83: only safety charging may be bounded to the original price
    # window; reserve two minutes for the battery mode-switch. Do not claim
    # that a shortfall was charged. Alpha84: later individually valid windows
    # remain eligible (no blanket block after a bounded charge).
    if action == "laden" and purpose == "veiligheidsladen":
        available_h = duration_h - 2.0 / 60.0
        if available_h <= 0 or limit < MIN_POWER_W:
            return None, "automatic_safety_window_unfeasible"
        feasible_energy = math.floor((limit * available_h / 1000.0 + EPS) * 1000.0) / 1000.0
        if feasible_energy < requested_energy - EPS:
            if feasible_energy <= EPS:
                return None, "automatic_safety_window_unfeasible"
            energy = feasible_energy
        average_power = energy * 1000.0 / available_h
    elif average_power > limit + EPS:
        return None, "automatic_power_above_configured_limit"
    # Preserve 10 W steps without allowing an excessive limit to be rounded
    # upward. R6 is planning-only and never executes an actuation.
    power = max(MIN_POWER_W, math.ceil((average_power - EPS) / 10.0) * 10.0)
    if power > limit + EPS or power > 3500.0:
        return None, "automatic_power_out_of_slot_range"
    if capacity_kwh <= 0.0 or not 0.0 < charge_efficiency <= 1.0 or not 0.0 < discharge_efficiency <= 1.0:
        return None, "battery_contract_invalid"
    start_soc = _finite(first.get("start_soc_percent"))
    delta = (
        energy * charge_efficiency / capacity_kwh * 100.0
        if action == "laden"
        else -energy / discharge_efficiency / capacity_kwh * 100.0
    )
    target_soc = start_soc + delta
    if not 5.0 <= target_soc <= 100.0:
        return None, "automatic_target_soc_out_of_range"
    starts = [item["_start"].isoformat() for item in segment]
    identity = "|".join((action, purpose, ",".join(starts), end.isoformat()))
    signature = "|".join(
        (identity, f"{target_soc:.3f}", f"{energy:.6f}", f"{power:.1f}")
    )
    price_sources = sorted({str(item.get("price_source") or "unknown") for item in segment})
    return {
        "action": action,
        "purpose": purpose,
        "execution_mode": "gepland",
        "start_time": start.isoformat(),
        "planned_end_time": end.isoformat(),
        "requested_energy_kwh": round(requested_energy, 6),
        "planned_energy_kwh": round(energy, 6),
        "energy_shortfall_kwh": round(max(0.0, requested_energy - energy), 6),
        "power_w": power,
        "target_soc": round(target_soc, 3),
        "max_runtime_h": round(duration_h, 4),
        "max_start_delay_min": START_DELAY_MIN,
        "origin": AUTO_ORIGIN,
        "planner_identity": identity,
        "planner_signature": signature,
        "price_sources": price_sources,
        "all_prices_known": price_sources == ["known"],
    }, None


def build_automatic_slot_proposals(
    combined: Mapping[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Build *all* future windows; the store chooses at most three free slots.

    R5 must be fully ready before calling this adapter. Never truncate source
    horizon or run an additional hourly / planner optimization.
    """
    if now.tzinfo is None:
        return {"valid": False, "reason": "now_timezone_required", "proposals": []}
    if combined.get("status") != "ready" or combined.get("valid") is not True:
        return {"valid": False, "reason": "combined_not_ready", "proposals": []}
    rows = combined.get("native_slots")
    if not isinstance(rows, list) or len(rows) != 288 or combined.get("native_slot_count") != 288:
        return {"valid": False, "reason": "combined_not_288_slots", "proposals": []}
    try:
        capacity_kwh = _finite(combined["capacity_kwh"])
        charge_eff = _finite(combined["charge_efficiency_percent"]) / 100.0
        discharge_eff = _finite(combined["discharge_efficiency_percent"]) / 100.0
        max_charge_w = _finite(combined["max_charge_power_w"])
        max_discharge_w = _finite(combined["max_discharge_power_w"])
        if capacity_kwh <= 0.0 or min(charge_eff, discharge_eff) <= 0.0:
            raise ValueError("invalid_capacity_or_efficiency")
        normalized: list[dict[str, Any]] = []
        prev_end = None
        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping) or int(raw.get("index", -1)) != index:
                raise ValueError("invalid_native_index")
            start, end = _utc(raw["start"]), _utc(raw["end"])
            if end - start != RESOLUTION or start.second or start.microsecond or start.minute % 15:
                raise ValueError("invalid_native_quarter_boundary")
            if prev_end is not None and start != prev_end:
                raise ValueError("native_slot_gap")
            prev_end = end
            normalized.append({**raw, "_start": start, "_end": end})
    except (KeyError, ValueError, TypeError, OverflowError) as err:
        return {"valid": False, "reason": f"source_contract_invalid:{err}", "proposals": []}

    now_utc = now.astimezone(timezone.utc)
    segments: list[list[dict[str, Any]]] = []
    active: list[dict[str, Any]] = []
    rejected: list[str] = []

    def flush() -> None:
        nonlocal active
        if active:
            segments.append(active)
            active = []

    for row in normalized:
        # R5 Combined has already reserved Manual time. R6 may never compete
        # with any portion of a manually committed native quarter.
        if row["_start"] <= now_utc or row.get("manual_slots") or _finite(row.get("manual_overlap_seconds") or 0.0) > EPS:
            flush()
            continue
        try:
            action_info = _extract(row)
        except (TypeError, ValueError) as err:
            rejected.append(f"quarter_{row['index']}:{err}")
            flush()
            continue
        if action_info is None:
            flush()
            continue
        action, purpose, energy = action_info
        current = {**row, "_action": action, "_purpose": purpose, "_energy": energy}
        if active and (
            active[-1]["_end"] != row["_start"]
            or active[-1]["_action"] != action
            or active[-1]["_purpose"] != purpose
        ):
            flush()
        active.append(current)
    flush()

    proposals: list[dict[str, Any]] = []
    for segment in segments:
        try:
            proposal, reason = _segment_to_proposal(
                segment,
                capacity_kwh=capacity_kwh,
                charge_efficiency=charge_eff,
                discharge_efficiency=discharge_eff,
                max_charge_power_w=max_charge_w,
                max_discharge_power_w=max_discharge_w,
            )
            if proposal:
                proposals.append(proposal)
            elif reason:
                rejected.append(f"window_{segment[0]['_start'].isoformat()}:{reason}")
                # Alpha83/84: keep earlier valid actions, but never publish
                # later candidates across a genuinely invalid chronological
                # predecessor. A merely limited feasible charge is valid.
                break
        except (ValueError, TypeError) as err:
            rejected.append(f"window_{segment[0]['_start'].isoformat()}:{err}")
            break

    proposals.sort(key=lambda item: (item["start_time"], item["planner_identity"]))
    return {
        "valid": True,
        "reason": "ready",
        "proposals": proposals,
        "window_count": len(segments),
        "rejected": rejected,
        "source_native_slot_count": len(rows),
        "physical_execution_enabled": False,
        "scheduler_enabled": False,
    }
