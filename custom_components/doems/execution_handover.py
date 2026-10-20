"""Pure R8 handover readiness gate.

This gate never authorizes battery actuation. It only records the independently
verified prerequisites needed before a future physical controller can be wired.
"""
from __future__ import annotations

from typing import Any, Mapping


def assess_handover(*, control_path: Mapping[str, Any],
                    command_contract_verified: bool = False,
                    exclusive_authority_verified: bool = False,
                    restart_reconciled: bool = False,
                    live_stop_test_passed: bool = False) -> dict[str, Any]:
    blockers: list[str] = []
    if control_path.get("ready") is not True:
        blockers.append("control_path_not_ready")
    if not command_contract_verified:
        blockers.append("command_contract_not_verified")
    if not exclusive_authority_verified:
        blockers.append("exclusive_authority_not_verified")
    if not restart_reconciled:
        blockers.append("restart_reconciliation_not_verified")
    if not live_stop_test_passed:
        blockers.append("live_stop_not_verified")
    return {
        "ready_for_handover": not blockers,
        "blockers": blockers,
        # Readiness alone is never an authority grant.
        "physical_execution_enabled": False,
        "execution_authority": False,
    }
