"""Pure backend validation for DOEMS EMS configuration fields."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any

from .const import (
    CONF_AWAY_END,
    CONF_AWAY_SCHEDULE_ENABLED,
    CONF_AWAY_START,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_CHARGE_EFFICIENCY_PERCENT,
    CONF_DISCHARGE_EFFICIENCY_PERCENT,
    CONF_MAX_CHARGE_POWER_W,
    CONF_MAX_DISCHARGE_POWER_W,
    CONF_MAX_SOC_PERCENT,
    CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
    CONF_SOFTWARE_RESERVE_PERCENT,
    CONF_STARTUP_DELAY_SECONDS,
    CONF_TECHNICAL_MIN_SOC_PERCENT,
)

ERR_INVALID_NUMBER = "ems_invalid_number"
ERR_BELOW_MINIMUM = "ems_below_minimum"
ERR_ABOVE_MAXIMUM = "ems_above_maximum"
ERR_INVALID_STEP = "ems_invalid_step"
ERR_INVALID_BOOLEAN = "ems_invalid_boolean"
ERR_INVALID_DATETIME = "ems_invalid_datetime"
ERR_SOC_RANGE_INVALID = "ems_soc_range_invalid"
ERR_AWAY_START_REQUIRED = "ems_away_start_required"
ERR_AWAY_END_REQUIRED = "ems_away_end_required"
ERR_AWAY_END_NOT_AFTER_START = "ems_away_end_not_after_start"

_NUMERIC_RULES: dict[str, tuple[Decimal, Decimal, Decimal, bool]] = {
    CONF_BATTERY_CAPACITY_KWH: (Decimal("1.0"), Decimal("30.0"), Decimal("0.1"), False),
    CONF_TECHNICAL_MIN_SOC_PERCENT: (Decimal("0"), Decimal("30"), Decimal("1"), True),
    CONF_MAX_SOC_PERCENT: (Decimal("50"), Decimal("100"), Decimal("1"), True),
    CONF_MAX_CHARGE_POWER_W: (Decimal("100"), Decimal("3500"), Decimal("100"), True),
    CONF_MAX_DISCHARGE_POWER_W: (Decimal("100"), Decimal("3500"), Decimal("100"), True),
    CONF_SOFTWARE_RESERVE_PERCENT: (Decimal("0"), Decimal("30"), Decimal("1"), False),
    CONF_CHARGE_EFFICIENCY_PERCENT: (Decimal("50"), Decimal("100"), Decimal("1"), False),
    CONF_DISCHARGE_EFFICIENCY_PERCENT: (Decimal("50"), Decimal("100"), Decimal("1"), False),
    CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH: (Decimal("0.00"), Decimal("1.00"), Decimal("0.01"), False),
    CONF_STARTUP_DELAY_SECONDS: (Decimal("30"), Decimal("300"), Decimal("5"), True),
}


def _as_decimal(value: Any) -> Decimal | None:
    """Convert numeric input without silently accepting booleans or non-finite values."""
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    try:
        if not isfinite(float(number)):
            return None
    except (OverflowError, ValueError):
        return None
    return number


def _valid_datetime(value: Any) -> bool:
    """Return whether an optional value is a complete parseable date/time."""
    if value in (None, ""):
        return True
    if isinstance(value, datetime):
        return True
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or ":" not in candidate or ("T" not in candidate and " " not in candidate):
        return False
    try:
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a previously field-validated date/time value."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def validate_ems_combination(values: dict[str, Any]) -> dict[str, str]:
    """Validate Step 4B relationships between individually valid EMS fields."""
    errors: dict[str, str] = {}

    min_soc = _as_decimal(values.get(CONF_TECHNICAL_MIN_SOC_PERCENT))
    max_soc = _as_decimal(values.get(CONF_MAX_SOC_PERCENT))
    if min_soc is not None and max_soc is not None and min_soc >= max_soc:
        errors[CONF_MAX_SOC_PERCENT] = ERR_SOC_RANGE_INVALID

    if values.get(CONF_AWAY_SCHEDULE_ENABLED) is True:
        start_value = values.get(CONF_AWAY_START)
        end_value = values.get(CONF_AWAY_END)
        if start_value in (None, ""):
            errors[CONF_AWAY_START] = ERR_AWAY_START_REQUIRED
        if end_value in (None, ""):
            errors[CONF_AWAY_END] = ERR_AWAY_END_REQUIRED
        if not errors.get(CONF_AWAY_START) and not errors.get(CONF_AWAY_END):
            start = _parse_datetime(start_value)
            end = _parse_datetime(end_value)
            if start is not None and end is not None and end <= start:
                errors[CONF_AWAY_END] = ERR_AWAY_END_NOT_AFTER_START

    return errors


def validate_ems_field(key: str, value: Any) -> str | None:
    """Validate one EMS configuration field without comparing it to other fields."""
    rule = _NUMERIC_RULES.get(key)
    if rule is not None:
        minimum, maximum, step, integer_only = rule
        number = _as_decimal(value)
        if number is None:
            return ERR_INVALID_NUMBER
        if integer_only and number != number.to_integral_value():
            return ERR_INVALID_STEP
        if number < minimum:
            return ERR_BELOW_MINIMUM
        if number > maximum:
            return ERR_ABOVE_MAXIMUM
        if (number - minimum) % step != 0:
            return ERR_INVALID_STEP
        return None

    if key == CONF_AWAY_SCHEDULE_ENABLED:
        return None if isinstance(value, bool) else ERR_INVALID_BOOLEAN

    if key in (CONF_AWAY_START, CONF_AWAY_END):
        return None if _valid_datetime(value) else ERR_INVALID_DATETIME

    return None


EMS_VALIDATED_FIELDS = (
    CONF_BATTERY_CAPACITY_KWH,
    CONF_TECHNICAL_MIN_SOC_PERCENT,
    CONF_MAX_SOC_PERCENT,
    CONF_MAX_CHARGE_POWER_W,
    CONF_MAX_DISCHARGE_POWER_W,
    CONF_SOFTWARE_RESERVE_PERCENT,
    CONF_CHARGE_EFFICIENCY_PERCENT,
    CONF_DISCHARGE_EFFICIENCY_PERCENT,
    CONF_MINIMUM_TRADE_MARGIN_EUR_PER_KWH,
    CONF_STARTUP_DELAY_SECONDS,
    CONF_AWAY_SCHEDULE_ENABLED,
    CONF_AWAY_START,
    CONF_AWAY_END,
)
