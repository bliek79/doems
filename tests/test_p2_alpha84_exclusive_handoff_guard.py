"""P2 fail-closed contract for the standalone DOEMS single-controller gate.

This test prevents a misleading ON state in the user-facing master switch.
It must NOT be 'fixed' by turning on physical authority in production.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOEMS = ROOT / "custom_components" / "doems"


def test_p2_master_gate_requires_exclusive_verified_authority_before_on():
    source = (DOEMS / "combined_execution_shadow_runtime.py").read_text()
    tree = ast.parse(source)
    runtime = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef)
                   and node.name == "DOEMSCombinedExecutionShadowRuntime")
    master = next(node for node in runtime.body
                  if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "async_set_master_enabled")
    text = ast.get_source_segment(source, master)
    assert "self._authority" in text
    assert "self.adapter.authority" in text
    assert "self._exclusive_claimed" in text
    assert "self.claim_exclusive_authority()" in text
    assert "self._combined_bridge is not None" in text
    assert "verified exclusive authority handoff required" in text
    assert text.index("verified exclusive authority handoff required") < text.index("self._master_enabled = True")


def test_p2_unapproved_main_stays_nonactuating_without_legacy_handoff():
    init = (DOEMS / "__init__.py").read_text()
    runtime = (DOEMS / "combined_execution_shadow_runtime.py").read_text()
    # No implicit master grant; R9 keeps its separate planner bridge non-actuating.
    assert "DOEMSCombinedExecutionShadowRuntime(" in init
    assert "authority=False, exclusive=False" in runtime
    assert "self._master_enabled = False" in runtime
