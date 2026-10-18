"""R8 handover readiness cannot itself grant physical authority."""
from custom_components.doems.execution_handover import assess_handover


def test_handover_fail_closed_without_evidence():
    result = assess_handover(control_path={"ready": False})
    assert result["ready_for_handover"] is False
    assert len(result["blockers"]) == 5
    assert result["physical_execution_enabled"] is False
    assert result["execution_authority"] is False


def test_handover_evidence_still_does_not_enable_actuation():
    result = assess_handover(
        control_path={"ready": True},
        command_contract_verified=True,
        exclusive_authority_verified=True,
        restart_reconciled=True,
        live_stop_test_passed=True,
    )
    assert result["ready_for_handover"] is True
    assert result["blockers"] == []
    assert result["physical_execution_enabled"] is False
    assert result["execution_authority"] is False


def test_handover_missing_exclusive_control_blocks():
    result = assess_handover(
        control_path={"ready": True},
        command_contract_verified=True,
        exclusive_authority_verified=False,
        restart_reconciled=True,
        live_stop_test_passed=True,
    )
    assert result["blockers"] == ["exclusive_authority_not_verified"]
