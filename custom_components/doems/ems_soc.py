"""Pure helpers for the generic read-only EMS SOC input contract."""
from __future__ import annotations

from typing import Any

UNAVAILABLE_SOC_STATES = {"unknown", "unavailable", "none", "None", ""}


def parse_soc_percent(value: Any) -> float | None:
    """Return a finite 0..100 SOC percentage or None for unusable input."""
    if value is None or str(value) in UNAVAILABLE_SOC_STATES:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not 0.0 <= parsed <= 100.0:
        return None
    return parsed
