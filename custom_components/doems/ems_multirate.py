"""DOEMS Alpha39 commitment-aware Design C multi-rate planner runtime helpers.

The production policy combines Anker Alpha80 cheapest-energy planning with the
DOEMS Alpha38 split reserve/safety reachability authority.  This module keeps the native
15-minute/event-driven heavy planner isolated from the fast execution/safety
cadence.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

from homeassistant.util import dt as dt_util

from .ems_alpha36_adapter import SOURCE_TAG, planner_reference, run_ems_chain

MULTIRATE_RUNTIME_VERSION = "alpha39_multirate_runtime_v1"
PLANNER_POLICY_VERSION = SOURCE_TAG
PLANNER_TRIGGERS = frozenset(
    {
        "startup",
        "quarter_boundary",
        "energy_forecast_update",
        "solar_forecast_update",
        "prices_forecast_update",
        "soc_recovered",
        "forecast_recovered",
        "start_critical",
    }
)

_SETTINGS_FIELDS = (
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
)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def planner_cycle_id(reference: datetime) -> str:
    """Return the native 15-minute UTC planner-cycle identity."""
    reference_utc = reference.astimezone(dt_util.UTC)
    minute = (reference_utc.minute // 15) * 15
    return reference_utc.replace(
        minute=minute,
        second=0,
        microsecond=0,
    ).isoformat()


def planner_input_signature(
    *,
    input_result: dict[str, Any],
    settings: Any,
    soc_percent: float,
    reference: datetime,
) -> str:
    """Hash policy-relevant input for one native quarter.

    The exact wall-clock second is deliberately excluded.  Duplicate source
    callbacks inside the same native quarter therefore cannot trigger repeated
    heavy planning for identical content.
    """
    settings_payload = {
        field: getattr(settings, field, None)
        for field in _SETTINGS_FIELDS
    }
    policy_reference = planner_reference(input_result, reference)
    payload = {
        "runtime": MULTIRATE_RUNTIME_VERSION,
        "policy": PLANNER_POLICY_VERSION,
        "cycle": planner_cycle_id(policy_reference),
        "soc_percent": float(soc_percent),
        "settings": settings_payload,
        "rows": input_result.get("rows") or [],
        "time_contract": input_result.get("time_contract") or {},
        "planner_start": input_result.get("planner_start"),
        "window_start": input_result.get("window_start"),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_planner_trigger(trigger: str) -> bool:
    """Return whether a trigger may start a heavy planner generation."""
    return trigger in PLANNER_TRIGGERS or trigger.startswith("planner_")


def run_planner_worker(
    *,
    input_result: dict[str, Any],
    settings: Any,
    soc_percent: float,
    reference: datetime,
    commitments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the Alpha39 commitment-aware Design C policy in a worker thread."""
    return run_ems_chain(
        input_result=input_result,
        settings=settings,
        soc_percent=soc_percent,
        now=reference,
        commitments=commitments or [],
    )
