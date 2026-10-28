"""Pure measured-energy accumulator for R8 automatic execution parity."""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any


def sample_energy(state: dict[str, Any], now: datetime, measured_power_w: Any) -> dict[str, Any]:
    """Integrate positive measured watts, bounding each gap to 60 s (Alpha84).

    No extrapolation when data is missing. Caller supplies battery action's
    measured direction, not a command setpoint.
    """
    try:
        power = float(measured_power_w)
        if not isfinite(power) or power < 0:
            return dict(state)
    except (TypeError, ValueError, OverflowError):
        return dict(state)
    new = dict(state)
    old_at, old_w = new.get("at"), new.get("power_w")
    if isinstance(old_at, datetime) and old_w is not None and old_at.tzinfo and now.tzinfo:
        seconds = max(0.0, min(60.0, (now - old_at).total_seconds()))
        new["energy_wh"] = float(new.get("energy_wh", 0)) + (float(old_w) + power) * 0.5 * seconds / 3600
    new["at"] = now
    new["power_w"] = power
    return new


def planned_energy_reached(state: dict[str, Any], planned_kwh: Any) -> bool:
    try:
        requested = float(planned_kwh)
        actual = float(state.get("energy_wh", 0)) / 1000
        return isfinite(requested) and requested > 0 and isfinite(actual) and actual + 0.002 >= requested
    except (TypeError, ValueError, OverflowError):
        return False
