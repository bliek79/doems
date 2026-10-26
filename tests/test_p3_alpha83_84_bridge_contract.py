"""P3 baseline: guard original 288-quarter bridge and Alpha83/84 scenarios.

These are read-only architecture checks; implementation of partial charge and
shortfall reporting follows after reference comparison.
"""
from pathlib import Path
import ast

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "doems"


def test_combined_bridge_preserves_quarter_source_and_manual_fence():
    source = (BASE / "automatic_slot_bridge_model.py").read_text()
    ast.parse(source)
    assert 'len(rows) != 288' in source
    assert 'row.get("manual_slots")' in source
    assert 'row.get("manual_overlap_seconds")' in source
    assert 'proposals.sort(key=lambda item: (item["start_time"], item["planner_identity"]))' in source


def test_slot_writer_checks_manual_revision_and_does_not_actuate():
    source = (BASE / "automatic_slot_bridge.py").read_text()
    ast.parse(source)
    assert "self._manual_pending" in source
    assert "serial != self._manual_serial" in source
    assert "async_release_expired_automatic_plans" in source
    assert '"physical_execution_enabled": False' in source


def test_p3_feasible_safety_charge_contract():
    source = (BASE / "automatic_slot_bridge_model.py").read_text()
    assert 'purpose == "veiligheidsladen"' in source
    assert 'duration_h - 2.0 / 60.0' in source
    assert '"requested_energy_kwh"' in source
    assert '"energy_shortfall_kwh"' in source
    assert "first_limited_index" not in source
