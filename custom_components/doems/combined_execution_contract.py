"""R9 Combined execution handoff contract. No physical control."""

from __future__ import annotations


def execution_handoff_status(shadow: dict) -> dict:
    """Only valid shadow slots can be considered for later handoff."""
    ready = shadow.get("status") == "shadow_ready"
    return {
        "ready_for_handoff_review": ready,
        "physical_execution_enabled": False,
        "execution_performed": False,
        "reason": "review_only" if ready else "shadow_blocked",
    }
