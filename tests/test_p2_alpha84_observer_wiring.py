"""P2 step 2: Combined observer actually consumes the Alpha84 projection."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "custom_components/doems/combined_execution_shadow_runtime.py"


def test_combined_runtime_uses_local_alpha84_guards_without_granting_authority():
    content = SRC.read_text()
    selected_path = content.split("        # Alpha84 guard code now runs locally", 1)[1]
    selected_path = selected_path.split("    def _identity(", 1)[0]
    assert "self._doems_prestart.evaluate(evidence)" in selected_path
    assert "self._doems_safety_guard.evaluate_automatic_handoff(evidence)" in selected_path
    assert "await legacy.async_refresh()" not in selected_path
    assert "inspected = inspect_alpha84_controller(" not in selected_path
    assert '"auto_bridge_candidates": [proof] if proof else []' in selected_path
    assert 'blockers.append("doems_alpha84_prestart_blocked")' in selected_path
    assert 'blockers.append("doems_alpha84_safety_guard_blocked")' in selected_path
    assert '"doems_alpha84_safety": independent_safety' in selected_path


def test_combined_projection_does_not_override_existing_nonactuating_flags():
    content = SRC.read_text()
    assert "authority=False, exclusive=False" in content
    assert "self._master_enabled = False" in content
    assert "self._authority = bool(authority)" in content


def test_doems_observer_has_no_live_anker_ems_registration():
    content = SRC.read_text()
    assert "OriginalAlpha84Registration" not in content
    assert "self.original_alpha84.register()" not in content
    assert "read_legacy_authority_fence" not in content
    assert "original_controller_registration" not in content
    assert "self._doems_prestart.evaluate(evidence)" in content
    assert "self._doems_safety_guard.evaluate_automatic_handoff(evidence)" in content


def test_local_alpha84_safety_is_read_only_and_fail_closed():
    content = SRC.read_text()
    assert "self._doems_prestart = AnkerEmsPreStartValidator()" in content
    assert "self._doems_safety_guard = AnkerEmsSafetyGuard()" in content
    assert '"status": "not_required_no_selected_plan"' in content
    assert 'independent_safety = {"status": "blocked", "physical_execution_enabled": False}' in content
    assert '"control_path_configured": False' in content
    assert '"physical_test_active": True' in content
    assert '"physical_execution_enabled": False' in content
    assert "authority=False, exclusive=False" in content
