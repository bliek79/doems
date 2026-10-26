"""Pure safety decision for clearing the historical EMS emergency result."""
from __future__ import annotations
from typing import Any


def check_execution_status_reset(
    execution: dict[str, Any],
    physical_test: dict[str, Any],
    *,
    automatic_armed: bool,
    operating_mode: str | None,
    power_state: str | None,
) -> str | None:
    """Return a blocker, or None. This NEVER changes physical controls."""
    if (execution.get("active") is not False
            or execution.get("auto_mode_switch_active") is not False):
        return "EMS-uitvoering of mode-switch is actief of niet betrouwbaar bevestigd"
    if physical_test.get("active") is not False:
        return "Fysieke test is actief of niet betrouwbaar bevestigd"
    if execution.get("status") != "emergency_stopped":
        return "Er is geen afgeronde noodstop om te bevestigen"
    if automatic_armed:
        return "Schakel eerst Dummy OS EMS Automatic Execution uit"
    if operating_mode != "self_consumption":
        return "Batterij moet eerst in self_consumption staan"
    if power_state is not None and str(power_state) not in {"unknown", "unavailable", "none", ""}:
        try:
            if abs(float(power_state)) > 0.5:
                return "Vermogenssetpoint is niet 0 W"
        except (ValueError, TypeError, OverflowError):
            return "Batterijsetpoint is ongeldig"
    # In self_consumption the Anker integration may mark its external
    # power control as unavailable; that is not evidence of an active command.
    return None
