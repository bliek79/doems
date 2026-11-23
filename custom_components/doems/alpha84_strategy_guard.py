"""H5.4 fail-closed Home Assistant setup check for original Anker Alpha84 owner.

No strategies, prices, SOC, action windows or physical device controls live
here. This only prevents starting DOEMS Plan72 with a replaced or missing
source bundle.
"""
from __future__ import annotations

from typing import Any


def original_alpha84_owner_present(worker_module: Any, original_factory: Any) -> bool:
    """Only the imported original Alpha84 source factory may own live planning."""
    return (
        original_factory is not None
        and getattr(worker_module, "compute_strategy_bundle", None) is original_factory
    )
