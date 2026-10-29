"""Energy Need Alpha7.7 read-only calculation tests."""
from datetime import datetime, timedelta, timezone
from custom_components.doems.energy_need import calculate_energy_need

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)

def slots(value):
    return [{"start": NOW + timedelta(minutes=15 * i), "energy_kwh": value(i) if callable(value) else value} for i in range(288)]

def run(home, solar, **changes):
    params = dict(now=NOW, soc_percent=60, capacity_kwh=7.1, min_soc_percent=5, reserve_percent=12)
    params.update(changes)
    return calculate_energy_need(home, solar, **params)

def test_sun_after_two_hours():
    result = run(slots(0.2), slots(lambda i: 0 if i < 8 else 0.3))
    assert result["valid"] and result["to_solar_kwh"] == 1.6
    assert result["horizon_hours"] == 2.0

def test_no_sun_uses_full_horizon():
    result = run(slots(0.1), slots(0))
    assert result["valid"] and result["horizon_hours"] == 72
    assert result["to_solar_kwh"] == 28.8 and result["tradable_battery_energy_kwh"] == 0

def test_missing_solar_blocks_trade():
    solar = slots(0.2)
    solar[5]["energy_kwh"] = None
    result = run(slots(0.3), solar)
    assert not result["valid"] and result["tradable_battery_energy_kwh"] is None

def test_zero_solar_does_not_count_as_usable():
    assert run(slots(0), slots(0))["next_usable_solar"] is None

def test_unknown_soc_blocks_balance():
    assert not run(slots(0.2), slots(0), soc_percent=None)["valid"]

def test_grid_charge_counts_efficiencies():
    result = run(slots(0.2), slots(0), soc_percent=5, charge_efficiency=0.8, discharge_efficiency=0.8)
    assert result["grid_charge_need_kwh"] > 72 * 0.2

def test_mid_quarter_uses_next_forecast_boundary():
    shifted = NOW + timedelta(minutes=8)
    home = [{"start": shifted.replace(minute=15) + timedelta(minutes=15 * i), "energy_kwh": 0.1} for i in range(288)]
    solar = [{"start": x["start"], "energy_kwh": 0} for x in home]
    result = run(home, solar, now=shifted)
    assert result["valid"] and result["horizon_hours"] == 72
