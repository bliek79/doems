"""Pure Energy Forecast source normalization for DOEMS."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from .const import (
    CONF_BATTERY_CHARGE_POWER_ENTITY,
    CONF_BATTERY_DISCHARGE_POWER_ENTITY,
    CONF_BATTERY_PRESENT,
    CONF_ENERGY_SOURCE_MODE,
    CONF_GRID_NET_POWER_ENTITY,
    CONF_GRID_SIGN_CONVENTION,
    CONF_HOME_POWER_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    ENERGY_SOURCE_BALANCE,
    ENERGY_SOURCE_DIRECT,
    GRID_SIGN_POSITIVE_EXPORT,
    GRID_SIGN_POSITIVE_IMPORT,
)


def normalize_power_w(value: Any, unit: str | None, *, allow_negative: bool) -> float | None:
    """Normalize one numeric W/kW value to watts."""
    if value in {None, "unknown", "unavailable", "none", ""}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if unit == "kW":
        number *= 1000.0
    elif unit not in {"W", None}:
        return None
    if not allow_negative and number < 0:
        return None
    return number


def normalize_grid_net_w(value_w: float, sign_convention: str) -> float:
    """Return signed grid power using positive import / negative export."""
    if sign_convention == GRID_SIGN_POSITIVE_IMPORT:
        return value_w
    if sign_convention == GRID_SIGN_POSITIVE_EXPORT:
        return -value_w
    raise ValueError(f"Unsupported grid sign convention: {sign_convention}")


def home_power_from_balance_w(
    *,
    grid_net_w: float,
    solar_w: float,
    battery_charge_w: float = 0.0,
    battery_discharge_w: float = 0.0,
) -> float:
    """Build canonical Home Power from the complete local power balance."""
    grid_import = max(grid_net_w, 0.0)
    grid_export = max(-grid_net_w, 0.0)
    return solar_w + grid_import + battery_discharge_w - grid_export - battery_charge_w


def configured_source_entities(options: dict[str, Any]) -> list[str]:
    """Return all physical input entity IDs required by the configured source mode."""
    mode = options.get(CONF_ENERGY_SOURCE_MODE)
    if mode == ENERGY_SOURCE_DIRECT:
        entity = options.get(CONF_HOME_POWER_ENTITY)
        return [entity] if entity else []
    if mode != ENERGY_SOURCE_BALANCE:
        return []
    entities = [
        options.get(CONF_GRID_NET_POWER_ENTITY),
        options.get(CONF_SOLAR_POWER_ENTITY),
    ]
    if options.get(CONF_BATTERY_PRESENT):
        entities.extend(
            [
                options.get(CONF_BATTERY_CHARGE_POWER_ENTITY),
                options.get(CONF_BATTERY_DISCHARGE_POWER_ENTITY),
            ]
        )
    return [entity for entity in entities if entity]


def source_signature(options: dict[str, Any]) -> str:
    """Return deterministic identity of source semantics used for stored learning data."""
    mode = options.get(CONF_ENERGY_SOURCE_MODE)
    payload: dict[str, Any] = {"mode": mode}
    if mode == ENERGY_SOURCE_DIRECT:
        payload["home_power_entity"] = options.get(CONF_HOME_POWER_ENTITY)
    elif mode == ENERGY_SOURCE_BALANCE:
        payload.update(
            {
                "grid_net_power_entity": options.get(CONF_GRID_NET_POWER_ENTITY),
                "grid_sign_convention": options.get(CONF_GRID_SIGN_CONVENTION),
                "solar_power_entity": options.get(CONF_SOLAR_POWER_ENTITY),
                "battery_present": bool(options.get(CONF_BATTERY_PRESENT)),
                "battery_charge_power_entity": options.get(CONF_BATTERY_CHARGE_POWER_ENTITY)
                if options.get(CONF_BATTERY_PRESENT)
                else None,
                "battery_discharge_power_entity": options.get(CONF_BATTERY_DISCHARGE_POWER_ENTITY)
                if options.get(CONF_BATTERY_PRESENT)
                else None,
            }
        )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(raw.encode("utf-8")).hexdigest()
