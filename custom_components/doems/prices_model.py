"""Pure provider-neutral price normalization helpers for DOEMS Prices P4.1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Iterable

QUARTER_MINUTES = 15
FORECAST_HORIZON_HOURS = 72
FORECAST_SLOTS = FORECAST_HORIZON_HOURS * 60 // QUARTER_MINUTES
PRICE_BUFFER_HOURS = 76
PRICE_BUFFER_SLOT_COUNT = PRICE_BUFFER_HOURS * 60 // QUARTER_MINUTES

PRICE_RESOLUTION_AUTO = "auto"
PRICE_RESOLUTION_15_MIN = "15_min"
PRICE_RESOLUTION_60_MIN = "60_min"
PRICE_RESOLUTION_OPTIONS = {
    PRICE_RESOLUTION_AUTO,
    PRICE_RESOLUTION_15_MIN,
    PRICE_RESOLUTION_60_MIN,
}

PRICE_SOURCE_PRIORITY = {
    "forecast_hour": 10,
    "known_hourly_fallback": 20,
    "known_pt15m": 30,
}


@dataclass(slots=True)
class PricePoint:
    """One normalized price slot."""

    start: datetime
    market_ex_vat: float
    market_incl_vat: float
    import_all_in: float
    export_all_in: float
    kind: str
    source_resolution_minutes: int
    lower_ex_vat: float | None = None
    upper_ex_vat: float | None = None
    forecast_generated_at: str | None = None
    uncertainty_pct: float | None = None
    regime: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "time": self.start.isoformat(),
            "market_ex_vat": self.market_ex_vat,
            "market_incl_vat": self.market_incl_vat,
            "import_all_in": self.import_all_in,
            "export_all_in": self.export_all_in,
            "kind": self.kind,
            "source_resolution_minutes": self.source_resolution_minutes,
            "lower_ex_vat": self.lower_ex_vat,
            "upper_ex_vat": self.upper_ex_vat,
            "forecast_generated_at": self.forecast_generated_at,
            "uncertainty_pct": self.uncertainty_pct,
            "regime": self.regime,
        }


def finite_float(value: Any) -> float | None:
    """Return one finite float or None."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_timestamp(value: Any) -> datetime | None:
    """Parse one provider timestamp and normalize it to aware UTC."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc(value: datetime) -> datetime:
    """Normalize an aware timestamp to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_aware_timestamp_required")
    return value.astimezone(timezone.utc)


def floor_quarter(value: datetime) -> datetime:
    """Floor an aware timestamp to the canonical UTC quarter."""
    value = utc(value)
    return value.replace(
        minute=(value.minute // QUARTER_MINUTES) * QUARTER_MINUTES,
        second=0,
        microsecond=0,
    )


def ceil_quarter(value: datetime) -> datetime:
    """Return the first canonical quarter boundary at or after the timestamp."""
    value = utc(value)
    floor = floor_quarter(value)
    return floor if floor == value else floor + timedelta(minutes=QUARTER_MINUTES)


def expected_quarter_starts(start: datetime, slot_count: int) -> list[datetime]:
    """Return exact consecutive slot starts without gap compression."""
    canonical = utc(start)
    return [
        canonical + timedelta(minutes=index * QUARTER_MINUTES)
        for index in range(int(slot_count))
    ]


def eur_mwh_to_kwh(value: Any) -> float | None:
    """Normalize EUR/MWh to EUR/kWh."""
    result = finite_float(value)
    return None if result is None else result / 1000.0


def compose_price_point(
    *,
    start: datetime,
    market_ex_vat: float,
    kind: str,
    source_resolution_minutes: int,
    vat_percent: float,
    import_supplier_incl_vat: float,
    import_tax_incl_vat: float,
    export_supplier_incl_vat: float,
    export_tax_incl_vat: float,
) -> PricePoint:
    """Build one normalized marginal import/export slot."""
    market = finite_float(market_ex_vat)
    vat = finite_float(vat_percent)
    import_supplier = finite_float(import_supplier_incl_vat)
    import_tax = finite_float(import_tax_incl_vat)
    export_supplier = finite_float(export_supplier_incl_vat)
    export_tax = finite_float(export_tax_incl_vat)
    if None in {market, vat, import_supplier, import_tax, export_supplier, export_tax}:
        raise ValueError("tariff_component_invalid")
    if not 0.0 <= float(vat) <= 100.0:
        raise ValueError("vat_percent_invalid")
    market_incl_vat = float(market) * (1.0 + float(vat) / 100.0)
    return PricePoint(
        start=utc(start),
        market_ex_vat=round(float(market), 6),
        market_incl_vat=round(market_incl_vat, 6),
        import_all_in=round(market_incl_vat + float(import_supplier) + float(import_tax), 6),
        export_all_in=round(market_incl_vat + float(export_supplier) + float(export_tax), 6),
        kind=str(kind),
        source_resolution_minutes=int(source_resolution_minutes),
    )


def deduplicate_price_points(
    points: Iterable[PricePoint],
) -> tuple[dict[datetime, PricePoint], int]:
    """Index by UTC slot start and retain the strongest provenance."""
    indexed: dict[datetime, PricePoint] = {}
    duplicate_count = 0
    for point in points:
        key = utc(point.start)
        existing = indexed.get(key)
        if existing is None:
            indexed[key] = point
            continue
        duplicate_count += 1
        if PRICE_SOURCE_PRIORITY.get(point.kind, 0) > PRICE_SOURCE_PRIORITY.get(existing.kind, 0):
            indexed[key] = point
    return indexed, duplicate_count


def select_exact_window(
    indexed: dict[datetime, PricePoint],
    *,
    start: datetime,
    slot_count: int,
) -> tuple[list[PricePoint], list[datetime]]:
    """Select exact expected timestamps; missing slots never shift later values."""
    selected: list[PricePoint] = []
    missing: list[datetime] = []
    for expected in expected_quarter_starts(start, slot_count):
        point = indexed.get(expected)
        if point is None:
            missing.append(expected)
        else:
            selected.append(point)
    return selected, missing


def build_price_index(
    prices_payload: dict[str, Any],
    forecast_payload: dict[str, Any],
    *,
    resolution_preference: str,
    vat_percent: float,
    import_supplier_incl_vat: float,
    import_tax_incl_vat: float,
    export_supplier_incl_vat: float,
    export_tax_incl_vat: float,
) -> tuple[dict[datetime, PricePoint], dict[str, Any]]:
    """Build one normalized provider-neutral index from Stroomvoorspeller payloads."""
    if resolution_preference not in PRICE_RESOLUTION_OPTIONS:
        raise ValueError("price_resolution_preference_invalid")

    point_kwargs = {
        "vat_percent": vat_percent,
        "import_supplier_incl_vat": import_supplier_incl_vat,
        "import_tax_incl_vat": import_tax_incl_vat,
        "export_supplier_incl_vat": export_supplier_incl_vat,
        "export_tax_incl_vat": export_tax_incl_vat,
    }

    hourly_known: dict[datetime, PricePoint] = {}
    if resolution_preference in {PRICE_RESOLUTION_AUTO, PRICE_RESOLUTION_60_MIN}:
        for item in prices_payload.get("prices") or []:
            start = parse_timestamp(item.get("time") or item.get("timestamp") or item.get("start"))
            market = eur_mwh_to_kwh(item.get("price"))
            if start is None or market is None:
                continue
            for quarter in range(4):
                q_start = start + timedelta(minutes=quarter * QUARTER_MINUTES)
                hourly_known[q_start] = compose_price_point(
                    start=q_start,
                    market_ex_vat=market,
                    kind="known_hourly_fallback",
                    source_resolution_minutes=60,
                    **point_kwargs,
                )

    pt15_raw = prices_payload.get("prices_15m") or []
    provider_has_pt15m = prices_payload.get("has_pt15m") is True and bool(pt15_raw)
    pt15_known: dict[datetime, PricePoint] = {}
    if resolution_preference in {PRICE_RESOLUTION_AUTO, PRICE_RESOLUTION_15_MIN} and provider_has_pt15m:
        for item in pt15_raw:
            start = parse_timestamp(item.get("time") or item.get("timestamp") or item.get("start"))
            market = eur_mwh_to_kwh(item.get("price"))
            if start is None or market is None:
                continue
            pt15_known[start] = compose_price_point(
                start=start,
                market_ex_vat=market,
                kind="known_pt15m",
                source_resolution_minutes=15,
                **point_kwargs,
            )

    known = dict(hourly_known)
    known.update(pt15_known)

    forecast_generated_at = forecast_payload.get("generated_at") or forecast_payload.get("generated")
    forecast: dict[datetime, PricePoint] = {}
    for item in forecast_payload.get("forecasts") or []:
        start = parse_timestamp(item.get("time") or item.get("timestamp") or item.get("start"))
        predicted = eur_mwh_to_kwh(item.get("predicted"))
        if start is None or predicted is None:
            continue
        lower = eur_mwh_to_kwh(item.get("lower"))
        upper = eur_mwh_to_kwh(item.get("upper"))
        uncertainty = finite_float(item.get("uncertainty_pct"))
        regime = item.get("regime")
        for quarter in range(4):
            q_start = start + timedelta(minutes=quarter * QUARTER_MINUTES)
            point = compose_price_point(
                start=q_start,
                market_ex_vat=predicted,
                kind="forecast_hour",
                source_resolution_minutes=60,
                **point_kwargs,
            )
            point.lower_ex_vat = lower
            point.upper_ex_vat = upper
            point.forecast_generated_at = str(forecast_generated_at) if forecast_generated_at else None
            point.uncertainty_pct = uncertainty
            point.regime = str(regime) if regime is not None else None
            forecast[q_start] = point

    indexed, duplicate_count = deduplicate_price_points([*forecast.values(), *known.values()])
    pt15_times = sorted(pt15_known)
    diagnostics = {
        "provider_has_pt15m": provider_has_pt15m,
        "pt15m_slots": len(pt15_known),
        "pt15m_first_time": pt15_times[0] if pt15_times else None,
        "pt15m_last_time": pt15_times[-1] if pt15_times else None,
        "known_slots": len(known),
        "forecast_slots": len(forecast),
        "duplicate_slots": duplicate_count,
        "resolution_preference": resolution_preference,
    }
    return indexed, diagnostics


def find_current_known_point(
    indexed: dict[datetime, PricePoint],
    *,
    now: datetime,
) -> PricePoint | None:
    """Return only the known point for the actual current quarter."""
    point = indexed.get(floor_quarter(now))
    if point is None or not point.kind.startswith("known_"):
        return None
    return point
