"""Pure Prices P4.1 contract helpers for DOEMS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .const import QUARTER_MINUTES

_PRICE_SOURCE_PRIORITY = {
    "forecast_hour": 10,
    "known_hourly_fallback": 20,
    "known_pt15m": 30,
}


@dataclass(slots=True)
class PricePoint:
    """One canonical 15-minute price slot."""

    start: datetime
    market_ex_vat: float | None
    market_incl_vat: float | None
    import_all_in: float | None
    export_all_in: float | None
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


def canonical_utc(value: datetime) -> datetime:
    """Return an aware timestamp in UTC."""
    if value.tzinfo is None:
        raise ValueError("price timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def floor_quarter(value: datetime) -> datetime:
    """Floor one aware timestamp to its absolute 15-minute boundary."""
    value = canonical_utc(value)
    return value.replace(
        minute=(value.minute // QUARTER_MINUTES) * QUARTER_MINUTES,
        second=0,
        microsecond=0,
    )


def expected_quarter_starts(start: datetime, slot_count: int) -> list[datetime]:
    """Return the exact positional slot timestamps for one consumer window."""
    start = canonical_utc(start)
    return [
        start + timedelta(minutes=index * QUARTER_MINUTES)
        for index in range(slot_count)
    ]


def compose_point(
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
    """Build a canonical point from market price plus directional tariffs."""
    market_incl_vat = market_ex_vat * (1.0 + vat_percent / 100.0)
    return PricePoint(
        start=canonical_utc(start),
        market_ex_vat=round(market_ex_vat, 6),
        market_incl_vat=round(market_incl_vat, 6),
        import_all_in=round(
            market_incl_vat + import_supplier_incl_vat + import_tax_incl_vat,
            6,
        ),
        export_all_in=round(
            market_incl_vat + export_supplier_incl_vat + export_tax_incl_vat,
            6,
        ),
        kind=kind,
        source_resolution_minutes=source_resolution_minutes,
    )


def deduplicate_price_points(
    points: Iterable[PricePoint],
) -> tuple[dict[datetime, PricePoint], int]:
    """Index by timestamp and retain the strongest known/forecast provenance."""
    indexed: dict[datetime, PricePoint] = {}
    duplicates = 0
    for point in points:
        key = canonical_utc(point.start)
        previous = indexed.get(key)
        if previous is None:
            indexed[key] = point
            continue
        duplicates += 1
        if _PRICE_SOURCE_PRIORITY.get(point.kind, 0) > _PRICE_SOURCE_PRIORITY.get(
            previous.kind, 0
        ):
            indexed[key] = point
    return indexed, duplicates


def select_exact_price_window(
    indexed: dict[datetime, PricePoint],
    *,
    start: datetime,
    slot_count: int,
) -> tuple[list[PricePoint], list[datetime]]:
    """Select exact expected timestamps without shifting around missing slots."""
    selected: list[PricePoint] = []
    missing: list[datetime] = []
    for expected in expected_quarter_starts(start, slot_count):
        point = indexed.get(expected)
        if point is None:
            missing.append(expected)
        else:
            selected.append(point)
    return selected, missing
