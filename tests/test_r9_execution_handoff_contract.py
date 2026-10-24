"""R9 execution handoff boundary tests."""
from custom_components.doems.combined_execution_contract import execution_handoff_status


def test_ready_shadow_does_not_enable_battery():
    result = execution_handoff_status({"status": "shadow_ready"})
    assert result["ready_for_handoff_review"] is True
    assert result["physical_execution_enabled"] is False
    assert result["execution_performed"] is False


def test_blocked_shadow_is_not_ready():
    result = execution_handoff_status({"status": "blocked"})
    assert result["ready_for_handoff_review"] is False
    assert result["physical_execution_enabled"] is False
