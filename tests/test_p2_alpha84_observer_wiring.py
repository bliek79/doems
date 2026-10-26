"""P2 step 2: Combined observer actually consumes the Alpha84 projection."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "custom_components/doems/combined_execution_shadow_runtime.py"


def test_combined_runtime_projects_slot_for_alpha84_without_granting_authority():
    content = SRC.read_text()
    assert "from .alpha84_handoff_contract import project_combined_slot" in content
    assert "inspected = inspect_alpha84_controller(" in content
    assert "await legacy.async_refresh()" in content
    assert "live_evidence=live_evidence" in content
    assert "sources_fresh=self.scheduler._sources_fresh" in content
    assert 'safety_safe=snapshot.get("status") == "ready"' in content
    assert '"alpha84_handoff": deepcopy(alpha84_handoff)' in content
    assert 'blockers.append("alpha84_original_safety_unverified")' in content


def test_combined_projection_does_not_override_existing_nonactuating_flags():
    content = SRC.read_text()
    assert "authority=False, exclusive=False" in content
    assert "self._master_enabled = False" in content
    assert "self._authority = bool(authority)" in content
