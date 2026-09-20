from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_invalid_slot_diagnostics_are_derived_from_existing_validity_rule() -> None:
    contract=(INTEGRATION/"ems_input_contract.py").read_text(encoding="utf-8")
    assert '("home", home)' in contract
    assert '("solar", solar)' in contract
    assert '("import_price", imp)' in contract
    assert '("export_price", exp)' in contract
    assert '"missing_inputs": missing_inputs' in contract
    assert '"invalid_slot_count": len(invalid_slots)' in contract
    assert '"first_invalid_slot": invalid_slots[0] if invalid_slots else None' in contract
    assert '"last_invalid_slot": invalid_slots[-1] if invalid_slots else None' in contract
    assert '"invalid_slots": invalid_slots' in contract


def test_288_fail_closed_gate_is_unchanged() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert 'input_result.get("native_valid_slot_count") != 288' in runtime
    assert 'self.status = "waiting_for_complete_forecast"' in runtime
    gate=runtime.index('input_result.get("native_valid_slot_count") != 288')
    planner=runtime.index('self.shadow_result = run_shadow_chain(')
    assert gate < planner


def test_ems_settings_sensor_listens_to_shadow_runtime() -> None:
    sensor=(INTEGRATION/"sensor.py").read_text(encoding="utf-8")
    assert 'self.shadow.async_add_listener(self._handle_shadow_update)' in sensor
    assert 'def _handle_shadow_update(self)' in sensor
    assert 'self.async_write_ha_state()' in sensor
