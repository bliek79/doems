from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load(name: str):
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    return importlib.import_module(f"custom_components.doems.{name}")


def _point(module, start: datetime):
    return module.PricePoint(
        start=start,
        market_ex_vat=0.10,
        market_incl_vat=0.121,
        import_all_in=0.30,
        export_all_in=0.10,
        kind="forecast_hour",
        source_resolution_minutes=60,
    )


def test_alpha62_shifted_planner_window_uses_304_slot_buffer() -> None:
    m = _load("prices_model")
    buffer_start = datetime(2026, 10, 7, 16, 30, tzinfo=timezone.utc)
    indexed = {
        ts: _point(m, ts)
        for ts in m.expected_quarter_starts(buffer_start, m.PRICE_BUFFER_SLOT_COUNT)
    }

    planner_reference = buffer_start + timedelta(minutes=30, seconds=5)
    planner_start = m.ceil_quarter(planner_reference)
    selected, missing = m.select_exact_price_window(
        indexed,
        start=planner_start,
        slot_count=m.FORECAST_SLOTS,
    )

    assert planner_start == buffer_start + timedelta(minutes=45)
    assert len(selected) == 288
    assert missing == []
    assert selected[0].start == planner_start
    assert selected[-1].start == planner_start + timedelta(minutes=15 * 287)


def test_alpha62_real_missing_buffer_quarter_stays_missing() -> None:
    m = _load("prices_model")
    start = datetime(2026, 10, 7, 17, 15, tzinfo=timezone.utc)
    indexed = {
        ts: _point(m, ts)
        for ts in m.expected_quarter_starts(start, m.FORECAST_SLOTS)
    }
    missing_start = start + timedelta(minutes=15 * 287)
    indexed.pop(missing_start)

    selected, missing = m.select_exact_price_window(
        indexed,
        start=start,
        slot_count=m.FORECAST_SLOTS,
    )
    assert len(selected) == 287
    assert missing == [missing_start]


def test_alpha62_wiring_reselects_prices_without_changing_control_path() -> None:
    prices = (INTEGRATION / "prices.py").read_text(encoding="utf-8")
    planner = (INTEGRATION / "automatic_planner.py").read_text(encoding="utf-8")
    policy = (INTEGRATION / "automatic_planner_model.py").read_text(encoding="utf-8")

    assert "def planner_timeline_slots(self, reference: datetime)" in prices
    assert "self._price_buffer_by_start" in prices
    assert "slot_count=FORECAST_SLOTS" in prices
    assert "self.prices.planner_timeline_slots(reference)" in planner
    assert "self.prices.timeline_slots" not in planner

    # R5 remains observational-only. No control path is opened by this hotfix.
    assert "automatic_plan_store_writes" in policy
    assert "physical_execution_authority" in policy
    assert "DOEMSScheduler" not in planner
    assert "async_call(" not in planner
    assert "third_party_control" not in planner


def test_alpha62_version_contract() -> None:
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    manifest = (INTEGRATION / "manifest.json").read_text(encoding="utf-8")
    assert 'VERSION = "0.2.0-alpha.6.2"' in const
    assert '"version": "0.2.0-alpha.6.2"' in manifest
