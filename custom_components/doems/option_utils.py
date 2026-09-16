"""Small type-safe helpers for DOEMS config-entry option handling."""

from __future__ import annotations

from typing import Any


def is_configured_option_value(value: Any) -> bool:
    """Return whether an option value counts as configured.

    The check deliberately avoids set membership because Solar Foundation options
    can be list- or dict-valued and therefore unhashable.
    """
    return value is not None and value != ""
