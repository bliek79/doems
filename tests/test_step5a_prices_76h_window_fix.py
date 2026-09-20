from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_prices_manager_exposes_quarter_aligned_buffer_window() -> None:
    prices=(INTEGRATION/"prices.py").read_text(encoding="utf-8")
    assert "def price_window(" in prices
    assert "window_start: datetime" in prices
    assert "slot_count: int = FORECAST_SLOTS" in prices
    assert "self._price_buffer_by_start.get(expected_start)" in prices
    assert 'raise ValueError("price window start must be quarter-aligned")' in prices


def test_ems_uses_same_window_start_for_energy_and_prices() -> None:
    live=(INTEGRATION/"ems_live_input.py").read_text(encoding="utf-8")
    assert "window_start = ceil_quarter(reference)" in live
    assert "coordinator.forecast(now=reference)" in live
    assert "prices.price_window(window_start=window_start, slot_count=288)" in live
    assert "prices.timeline_slots" not in live


def test_fix_preserves_fail_closed_contract() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert 'input_result.get("native_valid_slot_count") != 288' in runtime
    assert 'self.status = "waiting_for_complete_forecast"' in runtime
