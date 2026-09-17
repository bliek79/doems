from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom_components" / "doems" / "prices_model.py"
spec = importlib.util.spec_from_file_location("prices_model", MODULE)
prices_model = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = prices_model
spec.loader.exec_module(prices_model)


def _payloads() -> tuple[dict, dict]:
    return (
        {
            "has_pt15m": True,
            "prices": [
                {"time": "2026-09-17T10:00:00+00:00", "price": 100.0},
                {"time": "2026-09-17T11:00:00+00:00", "price": 200.0},
            ],
            "prices_15m": [
                {"time": "2026-09-17T10:00:00+00:00", "price": 80.0},
                {"time": "2026-09-17T10:15:00+00:00", "price": 90.0},
            ],
        },
        {
            "generated_at": "2026-09-17T09:55:00+00:00",
            "forecasts": [
                {"time": "2026-09-17T10:00:00+00:00", "predicted": 300.0, "lower": 250.0, "upper": 350.0, "uncertainty_pct": 12.5, "regime": "normal"},
                {"time": "2026-09-17T11:00:00+00:00", "predicted": 250.0},
                {"time": "2026-09-17T12:00:00+00:00", "predicted": 150.0},
            ],
        },
    )


def _build(preference: str):
    prices, forecast = _payloads()
    return prices_model.build_price_index(
        prices,
        forecast,
        resolution_preference=preference,
        vat_percent=21.0,
        import_supplier_incl_vat=0.01,
        import_tax_incl_vat=0.02,
        export_supplier_incl_vat=-0.03,
        export_tax_incl_vat=0.0,
    )


def test_auto_prefers_pt15_then_hourly_then_forecast() -> None:
    indexed, diagnostics = _build(prices_model.PRICE_RESOLUTION_AUTO)
    assert indexed[datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)].kind == "known_pt15m"
    assert indexed[datetime(2026, 9, 17, 10, 30, tzinfo=timezone.utc)].kind == "known_hourly_fallback"
    assert indexed[datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)].kind == "forecast_hour"
    assert diagnostics["pt15m_slots"] == 2


def test_15_min_preference_does_not_silently_use_hourly_known() -> None:
    indexed, _ = _build(prices_model.PRICE_RESOLUTION_15_MIN)
    assert indexed[datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)].kind == "known_pt15m"
    assert indexed[datetime(2026, 9, 17, 10, 30, tzinfo=timezone.utc)].kind == "forecast_hour"
    assert indexed[datetime(2026, 9, 17, 11, 0, tzinfo=timezone.utc)].kind == "forecast_hour"


def test_60_min_preference_ignores_pt15_known() -> None:
    indexed, diagnostics = _build(prices_model.PRICE_RESOLUTION_60_MIN)
    assert indexed[datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)].kind == "known_hourly_fallback"
    assert diagnostics["pt15m_slots"] == 0


def test_import_and_export_are_independent() -> None:
    indexed, _ = _build(prices_model.PRICE_RESOLUTION_AUTO)
    point = indexed[datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)]
    assert point.market_ex_vat == 0.08
    assert point.market_incl_vat == 0.0968
    assert point.import_all_in == 0.1268
    assert point.export_all_in == 0.0668


def test_exact_window_keeps_hole_position() -> None:
    start = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
    indexed = {}
    for idx in (0, 1, 3):
        stamp = start + timedelta(minutes=15 * idx)
        indexed[stamp] = prices_model.compose_price_point(
            start=stamp,
            market_ex_vat=0.1,
            kind="forecast_hour",
            source_resolution_minutes=60,
            vat_percent=21,
            import_supplier_incl_vat=0,
            import_tax_incl_vat=0,
            export_supplier_incl_vat=0,
            export_tax_incl_vat=0,
        )
    selected, missing = prices_model.select_exact_window(indexed, start=start, slot_count=4)
    assert [p.start for p in selected] == [start, start + timedelta(minutes=15), start + timedelta(minutes=45)]
    assert missing == [start + timedelta(minutes=30)]


def test_contract_constants() -> None:
    assert prices_model.QUARTER_MINUTES == 15
    assert prices_model.FORECAST_HORIZON_HOURS == 72
    assert prices_model.FORECAST_SLOTS == 288
    assert prices_model.PRICE_BUFFER_HOURS == 76
    assert prices_model.PRICE_BUFFER_SLOT_COUNT == 304


def test_current_price_never_uses_forecast() -> None:
    indexed, _ = _build(prices_model.PRICE_RESOLUTION_15_MIN)
    assert prices_model.find_current_known_point(indexed, now=datetime(2026, 9, 17, 10, 5, tzinfo=timezone.utc)).kind == "known_pt15m"
    assert prices_model.find_current_known_point(indexed, now=datetime(2026, 9, 17, 10, 35, tzinfo=timezone.utc)) is None
