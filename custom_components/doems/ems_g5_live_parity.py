"""Step 13 G5 frozen-live parity for DOEMS.

G5 is an acceptance diagnostic only. One already-materialized live DOEMS
snapshot is frozen and evaluated through two pure decision paths:

* golden: direct calls into the pinned/vendored Alpha76 decision core;
* doems: the production DOEMS Alpha41 compatibility adapter into that core.

The current DOEMS bridge decision is also evaluated from both Plan72 outputs
against the same frozen Scheduler/Plan Store surface so an upstream difference
is visible at the candidate-action boundary.

No Home Assistant state is read here, no Plan Store is mutated and no service
is called. This module can never obtain physical execution authority.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from .ems_alpha76.energy_need import build_energy_need_analysis
from .ems_alpha76.planner_72h import build_72h_plan_preview
from .ems_alpha76.planner_preview import build_planner_preview
from .ems_alpha76_adapter import (
    EXECUTION_BUFFER_PERCENT,
    SOURCE_TAG,
    forecast_from_input,
    planner_reference,
    run_energy_need,
    run_plan72,
    run_preview,
)
from .ems_planner_bridge import build_planner_action_bridge
from .ems_settings import EMSSettings

MAX_REPORTED_DIFFERENCES = 40
EXPECTED_TRANSPORT_ROWS = 72
EXPECTED_NATIVE_SLOTS = 288
EXPECTED_NATIVE_RESOLUTION_MINUTES = 15
EXPECTED_TRANSPORT_RESOLUTION_MINUTES = 60
POLICY_VERSION = "alpha76_baseline_v1"


def _jsonable(value: Any) -> Any:
    """Return a deterministic JSON-compatible representation."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def snapshot_fingerprint(snapshot: dict[str, Any]) -> str:
    """Hash the complete frozen input with stable ordering."""
    raw = json.dumps(
        _jsonable(snapshot),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _input_contract_blockers(input_result: Any) -> list[str]:
    """Validate the live 15m/72h/288 DOEMS planner-input contract."""
    if not isinstance(input_result, dict):
        return ["input_missing"]

    blockers: list[str] = []
    status = str(input_result.get("status") or "missing")
    if status != "ready":
        blockers.append(f"input_status_{status}")

    rows = input_result.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_TRANSPORT_ROWS:
        blockers.append("input_not_72_transport_rows")
    elif any(
        not isinstance(row, dict) or row.get("fully_valid") is not True
        for row in rows
    ):
        blockers.append("input_transport_rows_not_fully_valid")

    slots = input_result.get("slots")
    if not isinstance(slots, list) or len(slots) != EXPECTED_NATIVE_SLOTS:
        blockers.append("input_not_288_native_slots")
    elif any(
        not isinstance(slot, dict) or slot.get("valid") is not True
        for slot in slots
    ):
        blockers.append("input_native_slots_not_fully_valid")

    if input_result.get("native_expected_slot_count") != EXPECTED_NATIVE_SLOTS:
        blockers.append("input_native_expected_slot_count_not_288")
    if input_result.get("native_valid_slot_count") != EXPECTED_NATIVE_SLOTS:
        blockers.append("input_native_valid_slot_count_not_288")
    if input_result.get("planner_resolution_minutes") != EXPECTED_NATIVE_RESOLUTION_MINUTES:
        blockers.append("input_native_resolution_not_15")
    if input_result.get("transport_resolution_minutes") != EXPECTED_TRANSPORT_RESOLUTION_MINUTES:
        blockers.append("input_transport_resolution_not_60")
    if input_result.get("time_alignment_valid") is not True:
        blockers.append("input_time_alignment_invalid")

    contract = input_result.get("time_contract")
    if not isinstance(contract, dict):
        blockers.append("input_time_contract_missing")
    else:
        start = _aware(contract.get("window_start"))
        end = _aware(contract.get("window_end"))
        if start is None or end is None:
            blockers.append("input_time_contract_invalid")
        elif (end - start).total_seconds() != 72 * 3600:
            blockers.append("input_time_contract_not_72h")
        if contract.get("resolution_minutes") != EXPECTED_NATIVE_RESOLUTION_MINUTES:
            blockers.append("input_time_contract_resolution_not_15")
        if contract.get("slot_count") != EXPECTED_NATIVE_SLOTS:
            blockers.append("input_time_contract_slot_count_not_288")
        if contract.get("horizon_hours") != 72:
            blockers.append("input_time_contract_horizon_not_72")

    for source_blocker in input_result.get("blockers") or []:
        blockers.append(f"input_blocker:{source_blocker}")
    for runtime_blocker in input_result.get("runtime_blockers") or []:
        blockers.append(f"input_runtime_blocker:{runtime_blocker}")

    return sorted(set(blockers))


def _settings_from_snapshot(config: Any) -> tuple[EMSSettings | None, list[str]]:
    if not isinstance(config, dict):
        return None, ["config_missing"]

    required = {
        "battery_capacity_kwh",
        "technical_min_soc_percent",
        "max_soc_percent",
        "max_charge_power_w",
        "max_discharge_power_w",
        "software_reserve_percent",
        "charge_efficiency_percent",
        "discharge_efficiency_percent",
        "minimum_trade_margin_eur_per_kwh",
        "startup_delay_seconds",
    }
    missing = sorted(required - set(config))
    if missing:
        return None, [f"config_missing:{key}" for key in missing]

    try:
        settings = EMSSettings(
            battery_capacity_kwh=float(config["battery_capacity_kwh"]),
            technical_min_soc_percent=int(config["technical_min_soc_percent"]),
            max_soc_percent=int(config["max_soc_percent"]),
            max_charge_power_w=int(config["max_charge_power_w"]),
            max_discharge_power_w=int(config["max_discharge_power_w"]),
            software_reserve_percent=float(config["software_reserve_percent"]),
            charge_efficiency_percent=float(config["charge_efficiency_percent"]),
            discharge_efficiency_percent=float(config["discharge_efficiency_percent"]),
            minimum_trade_margin_eur_per_kwh=float(
                config["minimum_trade_margin_eur_per_kwh"]
            ),
            startup_delay_seconds=int(config["startup_delay_seconds"]),
        )
    except (TypeError, ValueError):
        return None, ["config_invalid"]
    return settings, []


def _bridge(
    plan72: dict[str, Any],
    *,
    settings: EMSSettings,
    scheduler_slots: dict[str | int, Any],
    reference: datetime,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        **deepcopy(plan72),
        "forecast_ready": True,
        "max_charge_power_w": settings.max_charge_power_w,
        "max_discharge_power_w": settings.max_discharge_power_w,
        "battery_capacity_kwh": settings.battery_capacity_kwh,
        "technical_min_soc_percent": settings.technical_min_soc_percent,
        "max_soc_percent": settings.max_soc_percent,
        "charge_efficiency_percent": settings.charge_efficiency_percent,
        "discharge_efficiency_percent": settings.discharge_efficiency_percent,
        "scheduler_slots": deepcopy(scheduler_slots),
    }
    return build_planner_action_bridge(data, now=reference)


def _golden_chain(
    input_result: dict[str, Any],
    soc_percent: float,
    settings: EMSSettings,
    scheduler_slots: dict[str | int, Any],
) -> dict[str, Any]:
    """Call the vendored/pinned Alpha76 decision functions directly."""
    forecast = forecast_from_input(deepcopy(input_result))
    reference = planner_reference(input_result)

    need = build_energy_need_analysis(
        forecast,
        soc_percent,
        settings.software_reserve_percent,
        battery_capacity_kwh=settings.battery_capacity_kwh,
        technical_min_soc_percent=settings.technical_min_soc_percent,
        max_soc_percent=settings.max_soc_percent,
        now=reference,
    )
    preview = build_planner_preview(
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
        now=reference,
    )
    plan72 = build_72h_plan_preview(
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
        now=reference,
    )
    bridge = _bridge(
        plan72,
        settings=settings,
        scheduler_slots=scheduler_slots,
        reference=reference,
    )
    return {
        "energy_need": need,
        "planner_preview": preview,
        "plan72": plan72,
        "bridge": bridge,
    }


def _doems_chain(
    input_result: dict[str, Any],
    soc_percent: float,
    settings: EMSSettings,
    scheduler_slots: dict[str | int, Any],
) -> dict[str, Any]:
    """Run the production DOEMS adapter path over the same frozen input."""
    reference = planner_reference(input_result)
    need = run_energy_need(
        input_result=deepcopy(input_result),
        settings=settings,
        soc_percent=soc_percent,
        now=reference,
    )
    preview = run_preview(
        input_result=deepcopy(input_result),
        settings=settings,
        energy_need=need,
        soc_percent=soc_percent,
        now=reference,
    )
    plan72 = run_plan72(
        input_result=deepcopy(input_result),
        settings=settings,
        energy_need=need,
        planner_preview=preview,
        soc_percent=soc_percent,
        now=reference,
    )
    bridge = _bridge(
        plan72,
        settings=settings,
        scheduler_slots=scheduler_slots,
        reference=reference,
    )
    return {
        "energy_need": need,
        "planner_preview": preview,
        "plan72": plan72,
        "bridge": bridge,
    }


def _difference_report(
    left: Any,
    right: Any,
    path: str = "$",
) -> tuple[int, list[str]]:
    """Return total structural difference count plus compact first paths."""
    total = 0
    reported: list[str] = []

    def add(message: str) -> None:
        nonlocal total
        total += 1
        if len(reported) < MAX_REPORTED_DIFFERENCES:
            reported.append(message)

    def walk(a: Any, b: Any, current: str) -> None:
        if type(a) is not type(b):
            add(f"{current}: type {type(a).__name__} != {type(b).__name__}")
            return
        if isinstance(a, dict):
            for key in sorted(set(a) | set(b), key=str):
                child = f"{current}.{key}"
                if key not in a:
                    add(f"{child}: missing in golden")
                elif key not in b:
                    add(f"{child}: missing in doems")
                else:
                    walk(a[key], b[key], child)
            return
        if isinstance(a, (list, tuple)):
            if len(a) != len(b):
                add(f"{current}: length {len(a)} != {len(b)}")
            for index, (item_a, item_b) in enumerate(zip(a, b, strict=False)):
                walk(item_a, item_b, f"{current}[{index}]")
            return
        if a != b:
            add(f"{current}: {a!r} != {b!r}")

    walk(left, right, path)
    return total, reported


def _decision_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    need = bundle.get("energy_need") or {}
    preview = bundle.get("planner_preview") or {}
    plan72 = bundle.get("plan72") or {}
    bridge = bundle.get("bridge") or {}

    candidates = bridge.get("auto_bridge_candidates") or []
    first_candidate = deepcopy(candidates[0]) if candidates else None
    if isinstance(first_candidate, dict):
        keep = {
            "action",
            "purpose",
            "start_time",
            "planned_end_time",
            "planned_energy_kwh",
            "power_w",
            "target_soc",
            "valid",
            "validation_reasons",
        }
        first_candidate = {
            key: value for key, value in first_candidate.items() if key in keep
        }

    return {
        "policy_version": POLICY_VERSION,
        "energy_need_valid": need.get("energy_need_valid"),
        "energy_need_reason": need.get("energy_need_reason"),
        "energy_need_until_solar_kwh": need.get("energy_need_until_solar_kwh"),
        "first_usable_solar": need.get("energy_need_first_usable_solar"),
        "additional_grid_charge_kwh": need.get(
            "energy_need_additional_grid_charge_kwh"
        ),
        "preview_status": preview.get("planner_preview_status"),
        "preview_decision": preview.get("planner_preview_decision"),
        "preview_reason": preview.get("planner_preview_reason"),
        "plan72_valid": plan72.get("auto_plan_72h_valid"),
        "plan72_reason": plan72.get("auto_plan_72h_reason"),
        "plan72_start_soc": plan72.get("auto_plan_72h_start_soc"),
        "plan72_end_soc": plan72.get("auto_plan_72h_end_soc"),
        "plan72_count": plan72.get("auto_plan_72h_count"),
        "bridge_status": bridge.get("auto_bridge_status"),
        "bridge_valid": bridge.get("auto_bridge_valid"),
        "bridge_reason": bridge.get("auto_bridge_reason"),
        "bridge_candidate_count": bridge.get("auto_bridge_candidate_count"),
        "first_candidate": first_candidate,
    }


def compare_frozen_live_snapshot(frozen_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one immutable G5 live snapshot without runtime side effects."""
    input_result = deepcopy(frozen_snapshot.get("input_result"))
    scheduler_slots = deepcopy(frozen_snapshot.get("scheduler_slots") or {})
    planner_soc = frozen_snapshot.get("planner_start_soc_percent")

    blockers = _input_contract_blockers(input_result)
    settings, settings_blockers = _settings_from_snapshot(
        frozen_snapshot.get("config")
    )
    blockers.extend(settings_blockers)

    try:
        planner_soc_value = float(planner_soc)
    except (TypeError, ValueError):
        planner_soc_value = None
        blockers.append("planner_soc_missing")
    if planner_soc_value is not None and not 0.0 <= planner_soc_value <= 100.0:
        blockers.append("planner_soc_invalid")

    fingerprint = snapshot_fingerprint(frozen_snapshot)
    blockers = sorted(set(blockers))
    if blockers:
        return {
            "status": "blocked",
            "exact_match": False,
            "snapshot_fingerprint": fingerprint,
            "policy_version": POLICY_VERSION,
            "blockers": blockers,
            "difference_count": 0,
            "differences": [],
            "differences_capped_at": MAX_REPORTED_DIFFERENCES,
            "shadow_only": True,
            "service_calls_performed": False,
            "plan_store_mutated": False,
            "physical_execution_authority": False,
            "cutover_permitted": False,
        }

    assert isinstance(input_result, dict)
    assert settings is not None
    assert planner_soc_value is not None

    golden = _golden_chain(
        input_result,
        planner_soc_value,
        settings,
        scheduler_slots,
    )
    doems = _doems_chain(
        input_result,
        planner_soc_value,
        settings,
        scheduler_slots,
    )
    difference_count, differences = _difference_report(golden, doems)
    exact = difference_count == 0

    return {
        "status": "pass" if exact else "mismatch",
        "exact_match": exact,
        "snapshot_fingerprint": fingerprint,
        "policy_version": POLICY_VERSION,
        "blockers": [],
        "difference_count": difference_count,
        "differences": differences,
        "differences_capped_at": MAX_REPORTED_DIFFERENCES,
        "golden_source": f"anker_ems {SOURCE_TAG} vendored decision baseline",
        "doems_path": "DOEMS 288x15m -> Alpha41 72x60m adapter -> Alpha76 core",
        "golden_decision": _decision_summary(golden),
        "doems_decision": _decision_summary(doems),
        "golden_raw": deepcopy(golden),
        "doems_raw": deepcopy(doems),
        "shadow_only": True,
        "service_calls_performed": False,
        "plan_store_mutated": False,
        "physical_execution_authority": False,
        "cutover_permitted": False,
    }
