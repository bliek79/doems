"""Pure DOEMS native 288-slot -> Alpha41 72-row compatibility contract."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any

SLOT_MINUTES = 15
SLOT_COUNT = 288
ROW_COUNT = 72
QUARTERS_PER_ROW = 4
STEP = timedelta(minutes=SLOT_MINUTES)

def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)

def _index(items: list[dict[str, Any]]) -> dict[datetime, dict[str, Any]]:
    result: dict[datetime, dict[str, Any]] = {}
    for item in items:
        start = _aware(item.get("start") or item.get("time"))
        if start is not None:
            result[start] = item
    return result

def build_alpha41_transport_input(
    *,
    window_start: datetime,
    energy_slots: list[dict[str, Any]],
    solar_slots: list[dict[str, Any]],
    price_slots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the proven rolling 72x60m view without clock-hour rounding."""
    start = _aware(window_start)
    if start is None or start.minute not in (0, 15, 30, 45) or start.second or start.microsecond:
        raise ValueError("window_start must be an exact aware quarter boundary")
    eidx, sidx, pidx = _index(energy_slots), _index(solar_slots), _index(price_slots)
    slots: list[dict[str, Any]] = []
    for index in range(SLOT_COUNT):
        slot_start = start + index * STEP
        e, s, p = eidx.get(slot_start), sidx.get(slot_start), pidx.get(slot_start)
        home = None if e is None else e.get("energy_kwh")
        solar = None if s is None else s.get("solar_kwh", s.get("total_kwh"))
        imp = None if p is None else p.get("import_price", p.get("import_all_in"))
        exp = None if p is None else p.get("export_price", p.get("export_all_in"))
        missing_inputs = [
            name
            for name, value in (
                ("home", home),
                ("solar", solar),
                ("import_price", imp),
                ("export_price", exp),
            )
            if value is None
        ]
        valid = not missing_inputs
        slots.append({
            "index": index,
            "start": slot_start.isoformat(),
            "end": (slot_start + STEP).isoformat(),
            "home_kwh": home,
            "solar_kwh": solar,
            "import_price": imp,
            "export_price": exp,
            "price_kind": None if p is None else p.get("kind"),
            "valid": valid,
            "missing_inputs": missing_inputs,
        })
    rows: list[dict[str, Any]] = []
    for row_index in range(ROW_COUNT):
        group = slots[row_index*4:(row_index+1)*4]
        fully_valid = all(item["valid"] for item in group)
        kinds = {item["price_kind"] for item in group if item["price_kind"]}
        source = "known" if kinds and all(str(k).startswith("known") for k in kinds) else ("forecast" if kinds else None)
        rows.append({
            "index": row_index,
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "home_kwh": round(sum(float(x["home_kwh"]) for x in group), 6) if fully_valid else None,
            "solar_kwh": round(sum(float(x["solar_kwh"]) for x in group), 6) if fully_valid else None,
            "import_price": round(sum(float(x["import_price"]) for x in group)/4.0, 6) if fully_valid else None,
            "export_price": round(sum(float(x["export_price"]) for x in group)/4.0, 6) if fully_valid else None,
            "price_source": source,
            "fully_valid": fully_valid,
            "quarter_count": 4,
        })
    invalid_slots = [
        {
            "index": slot["index"],
            "start": slot["start"],
            "missing_inputs": list(slot["missing_inputs"]),
        }
        for slot in slots
        if not slot["valid"]
    ]
    return {
        "status": "ready" if all(row["fully_valid"] for row in rows) else "partial",
        "rows": rows,
        "slots": slots,
        "planner_resolution_minutes": 15,
        "transport_resolution_minutes": 60,
        "native_expected_slot_count": SLOT_COUNT,
        "native_valid_slot_count": sum(1 for slot in slots if slot["valid"]),
        "invalid_slot_count": len(invalid_slots),
        "first_invalid_slot": invalid_slots[0] if invalid_slots else None,
        "last_invalid_slot": invalid_slots[-1] if invalid_slots else None,
        "invalid_slots": invalid_slots,
        "time_alignment_valid": True,
        "time_contract": {
            "window_start": start.isoformat(),
            "window_end": (start + timedelta(hours=72)).isoformat(),
            "resolution_minutes": 15,
            "slot_count": SLOT_COUNT,
            "horizon_hours": 72,
            "alignment_policy": "alpha41_rolling_quarter_start_no_clock_hour_rounding",
        },
        "physical_execution_authority": False,
    }
