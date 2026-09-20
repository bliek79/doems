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


def test_native_time_contract_is_15m_72h_288_and_buffer_304():
    m = _load("prices_model")
    start = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    slots = m.expected_quarter_starts(start, m.FORECAST_SLOTS)
    assert len(slots) == 288
    assert slots[-1] == start + timedelta(minutes=15 * 287)
    assert m.PRICE_BUFFER_SLOT_COUNT == 304


def test_known_pt15m_beats_hourly_fallback_and_forecast():
    m = _load("prices_model")
    start = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    forecast = m.PricePoint(start, 0.1, 0.121, 0.2, 0.15, "forecast_hour", 60)
    hourly = m.PricePoint(start, 0.2, 0.242, 0.3, 0.25, "known_hourly_fallback", 60)
    pt15 = m.PricePoint(start, 0.3, 0.363, 0.4, 0.35, "known_pt15m", 15)
    indexed, duplicates = m.deduplicate_price_points([forecast, hourly, pt15])
    assert duplicates == 2
    assert indexed[start].kind == "known_pt15m"


def test_import_and_export_are_separate_configurable_prices():
    m = _load("prices_model")
    start = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    point = m.compose_point(
        start,
        0.10,
        kind="known_pt15m",
        source_resolution_minutes=15,
        vat_percent=21.0,
        import_supplier_incl_vat=0.03,
        import_tax_incl_vat=0.10,
        export_supplier_incl_vat=-0.02,
        export_tax_incl_vat=0.00,
    )
    assert point.market_incl_vat == 0.121
    assert point.import_all_in == 0.251
    assert point.export_all_in == 0.101


def test_exact_window_does_not_shift_around_missing_slot():
    m = _load("prices_model")
    start = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    points = {}
    for idx, ts in enumerate(m.expected_quarter_starts(start, 4)):
        if idx == 1:
            continue
        points[ts] = m.PricePoint(ts, 0.1, 0.1, 0.2, 0.1, "forecast_hour", 60)
    selected, missing = m.select_exact_price_window(points, start=start, slot_count=4)
    assert len(selected) == 3
    assert missing == [start + timedelta(minutes=15)]
    assert selected[1].start == start + timedelta(minutes=30)


def test_ceil_quarter_keeps_exact_boundary_and_advances_partial_slot():
    m = _load("prices_model")
    exact = datetime(2026, 9, 17, 12, 15, tzinfo=timezone.utc)
    partial = datetime(2026, 9, 17, 12, 15, 1, tzinfo=timezone.utc)
    assert m.ceil_quarter(exact) == exact
    assert m.ceil_quarter(partial) == datetime(2026, 9, 17, 12, 30, tzinfo=timezone.utc)



def test_energyzero_gas_action_response_selects_current_market_point():
    m = _load("prices_model")
    now = datetime(2026, 9, 18, 7, 0, tzinfo=timezone.utc)
    value, timestamp, count = m.select_current_response_price(
        [{"timestamp": "2026-09-18T04:00:00+00:00", "price": 0.83127809154956}],
        now=now,
    )
    assert value == 0.83127809154956
    assert timestamp == "2026-09-18T04:00:00+00:00"
    assert count == 1


def test_energyzero_gas_action_response_supports_legacy_hourly_shape():
    m = _load("prices_model")
    now = datetime(2026, 9, 18, 7, 20, tzinfo=timezone.utc)
    value, timestamp, count = m.select_current_response_price(
        [
            {"timestamp": "2026-09-18T06:00:00+00:00", "price": 0.80},
            {"timestamp": "2026-09-18T07:00:00+00:00", "price": 0.81},
            {"timestamp": "2026-09-18T08:00:00+00:00", "price": 0.82},
        ],
        now=now,
    )
    assert value == 0.81
    assert timestamp == "2026-09-18T07:00:00+00:00"
    assert count == 3



def test_gas_equivalent_price_uses_fixed_higher_heating_value_basis():
    m = _load("prices_model")
    value = m.gas_equivalent_eur_kwh(
        1.711679,
        energy_factor_kwh_m3=9.77,
    )
    assert value == 0.175197


def test_electricity_to_gas_ratio_and_missing_semantics():
    m = _load("prices_model")
    assert m.electricity_to_gas_price_ratio(0.35, 0.175) == 2.0
    assert m.electricity_to_gas_price_ratio(None, 0.175) is None
    assert m.electricity_to_gas_price_ratio(0.35, None) is None
    assert m.electricity_to_gas_price_ratio(0.35, 0.0) is None
    assert m.gas_equivalent_eur_kwh(None, energy_factor_kwh_m3=9.77) is None
    assert m.gas_equivalent_eur_kwh(1.71, energy_factor_kwh_m3=0) is None


def test_price_window_rolls_inside_304_slot_buffer_without_losing_last_quarter():
    m = _load("prices_model")
    start = datetime(2026, 9, 20, 19, 0, tzinfo=timezone.utc)
    buffer_starts = m.expected_quarter_starts(start, m.PRICE_BUFFER_SLOT_COUNT)
    assert len(buffer_starts) == 304
    # A consumer moving one quarter forward still has a complete 288-slot window.
    shifted = start + timedelta(minutes=15)
    selected = [ts for ts in buffer_starts if shifted <= ts < shifted + timedelta(minutes=15 * 288)]
    assert len(selected) == 288
    assert selected[0] == shifted
    assert selected[-1] == shifted + timedelta(minutes=15 * 287)
