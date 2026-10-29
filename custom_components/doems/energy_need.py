"""Read-only quarter-hour Energy Need adapted from Anker EMS Alpha84."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from math import isfinite

def positive(value):
    try:
        n = float(value)
        return n if not isinstance(value, bool) and isfinite(n) and n >= 0 else None
    except (ValueError, TypeError):
        return None

def calculate_energy_need(home_slots, solar_slots, *, now, soc_percent, capacity_kwh, min_soc_percent, reserve_percent, charge_efficiency=0.92, discharge_efficiency=0.92):
    def failed(reason):
        return dict(status="waiting_for_complete_forecast", valid=False, reason=reason, to_solar_kwh=None, next_usable_solar=None, available_battery_energy_kwh=None, safety_reserve_kwh=None, required_energy_kwh=None, grid_charge_need_kwh=None, tradable_battery_energy_kwh=None, horizon_hours=None, matched_quarters=0, observational_only=True)
    if now.tzinfo is None or now.utcoffset() is None:
        return failed("invalid_timestamp")
    soc, capacity, minimum, reserve = map(positive, (soc_percent, capacity_kwh, min_soc_percent, reserve_percent))
    cin, cout = positive(charge_efficiency), positive(discharge_efficiency)
    if any(x is None for x in (soc, capacity, minimum, reserve, cin, cout)) or capacity <= 0 or soc > 100 or minimum > 100 or reserve > 100 or cin <= 0 or cin > 1 or cout <= 0 or cout > 1:
        return failed("invalid_battery_configuration")
    now = now.astimezone(timezone.utc)
    start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    stamps = [start + timedelta(minutes=15 * n) for n in range(288)]
    def by_time(slots):
        result = {}
        for item in slots:
            t = item.get("start")
            if isinstance(t, datetime) and t.tzinfo is not None and t.utcoffset() is not None:
                t = t.astimezone(timezone.utc)
                if t in result:
                    return {}
                result[t] = positive(item.get("energy_kwh"))
        return result
    home, solar = by_time(home_slots), by_time(solar_slots)
    if any(t not in home or t not in solar or home[t] is None or solar[t] is None for t in stamps):
        return failed("missing_or_incomplete_288_quarter_forecast")
    usable = next((i for i in range(285) if all(solar[stamps[j]] > 0 and solar[stamps[j]] >= home[stamps[j]] for j in range(i,i+4))), None)
    endpoint = usable if usable is not None else 288
    fractions = [max(0.0, min(1.0, (stamps[0]+timedelta(minutes=15)-now).total_seconds()/900))] + [1.] * 287
    demand = sum(max(home[stamps[i]]-solar[stamps[i]], 0) * fractions[i] for i in range(endpoint))
    available = capacity * max(soc-minimum, 0)/100
    extra_reserve = capacity * reserve/100
    required = demand + extra_reserve*cout
    shortage = max(required-available*cout, 0)
    return dict(status="ready", valid=True, reason="full_horizon_no_usable_solar" if usable is None else "shortage" if shortage > 1e-9 else "covered", to_solar_kwh=round(demand,3), next_usable_solar=stamps[usable].isoformat() if usable is not None else None, available_battery_energy_kwh=round(available,3), safety_reserve_kwh=round(extra_reserve,3), required_energy_kwh=round(required,3), grid_charge_need_kwh=round(shortage/(cin*cout),3), tradable_battery_energy_kwh=round(max(available-extra_reserve-demand/cout,0),3), horizon_hours=round(sum(fractions[:endpoint])/4,3), matched_quarters=288, observational_only=True)
