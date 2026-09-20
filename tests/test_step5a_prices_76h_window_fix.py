from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load_pure(name: str):
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    return importlib.import_module(f"custom_components.doems.{name}")


@dataclass
class _Energy:
    start: datetime
    energy_kwh: float


@dataclass
class _Solar:
    start: datetime
    total_kwh: float


class _Coordinator:
    def __init__(self, start: datetime) -> None:
        self.start = start

    def forecast(self, *, now: datetime):
        return [
            _Energy(self.start + timedelta(minutes=15*i), 0.1)
            for i in range(288)
        ]


class _SolarForecast:
    def __init__(self, start: datetime) -> None:
        self.points = [
            _Solar(start + timedelta(minutes=15*i), 0.05)
            for i in range(288)
        ]


class _Prices:
    def __init__(self, buffer_start: datetime) -> None:
        self.buffer = {}
        for i in range(304):
            start = buffer_start + timedelta(minutes=15*i)
            self.buffer[start] = {
                "time": start.isoformat(),
                "import_all_in": 0.25,
                "export_all_in": 0.10,
                "kind": "forecast_hour",
            }
        self.timeline_slots = [
            self.buffer[buffer_start + timedelta(minutes=15*i)]
            for i in range(288)
        ]
        self.requested_start = None
        self.requested_count = None

    def price_window(self, *, window_start: datetime, slot_count: int):
        self.requested_start = window_start
        self.requested_count = slot_count
        result = []
        for i in range(slot_count):
            start = window_start + timedelta(minutes=15*i)
            result.append(self.buffer.get(start, {
                "time": start.isoformat(),
                "import_all_in": None,
                "export_all_in": None,
                "kind": "missing",
            }))
        return result


def test_ems_uses_76h_price_buffer_for_shifted_72h_window() -> None:
    live = _load_pure("ems_live_input")
    buffer_start = datetime(2026, 9, 20, 19, 0, tzinfo=timezone.utc)
    reference = datetime(2026, 9, 20, 19, 1, tzinfo=timezone.utc)
    window_start = datetime(2026, 9, 20, 19, 15, tzinfo=timezone.utc)
    prices = _Prices(buffer_start)

    result = live.build_live_ems_input(
        coordinator=_Coordinator(window_start),
        solar_forecast=_SolarForecast(window_start),
        prices=prices,
        reference=reference,
    )

    assert prices.requested_start == window_start
    assert prices.requested_count == 288
    assert result["status"] == "ready"
    assert result["native_valid_slot_count"] == 288
    assert result["invalid_slot_count"] == 0
    assert result["prices_source"] == "doems_prices_76h_buffer_window"
    assert result["slots"][-1]["start"] == "2026-09-23T19:00:00+00:00"
    assert result["slots"][-1]["import_price"] == 0.25
    assert result["slots"][-1]["export_price"] == 0.10


def test_prices_manager_exposes_exact_buffer_window_without_padding() -> None:
    prices = (INTEGRATION / "prices.py").read_text(encoding="utf-8")
    assert "def price_window(" in prices
    assert "self._price_buffer_by_start.get(expected_start)" in prices
    assert '"kind": "missing"' in prices
    assert "slot_count > PRICE_BUFFER_SLOT_COUNT" in prices
    assert "price window start must be quarter-aligned" in prices


def test_fix_preserves_fail_closed_contract() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert 'input_result.get("native_valid_slot_count") != 288' in runtime
    assert 'self.status = "waiting_for_complete_forecast"' in runtime
