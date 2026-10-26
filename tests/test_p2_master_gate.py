"""P2 master gate contract: no implicit physical authority."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "doems"


def test_master_switch_registered_and_default_off():
    const = (ROOT / "const.py").read_text()
    runtime = (ROOT / "combined_execution_shadow_runtime.py").read_text()
    switch = (ROOT / "switch.py").read_text()
    assert '"switch"' in const.split("PLATFORMS =", 1)[1].split("\n", 1)[0]
    assert "self._master_enabled = False" in runtime
    assert "self._master_enabled and self._combined_bridge" in runtime
    assert "and self._master_enabled" in runtime
    assert "await self.runtime.async_set_master_enabled(False)" in switch
    assert "await self.runtime.async_set_master_enabled(True)" in switch


def test_switch_off_fences_existing_session():
    runtime = (ROOT / "combined_execution_shadow_runtime.py").read_text()
    assert "self._master_enabled = False" in runtime
    assert "if self.controller.session is not None or self.controller.reconciliation_required:" in runtime
    assert "await self.controller.stop()" in runtime
