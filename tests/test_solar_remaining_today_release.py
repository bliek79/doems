"""Regression contract for DOEMS 3.0 remaining-today Solar sensor."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOLAR_SENSOR = ROOT / "custom_components" / "doems" / "solar_sensor.py"
SOLAR_FORECAST = ROOT / "custom_components" / "doems" / "solar_forecast.py"


def test_remaining_today_is_registered_once_and_existing_today_is_preserved():
    source = SOLAR_SENSOR.read_text(encoding="utf-8")
    assert source.count("DOEMSSolarForecastRemainingTodaySensor(entry, manager)") == 1
    assert 'DOEMSSolarForecastDailySensor(entry, manager, "today")' in source
    assert 'DOEMSSolarForecastDailySensor(entry, manager, "tomorrow")' in source
    assert '_attr_unique_id = "doems_solar_forecast_remaining_today"' in source
    assert '_attr_suggested_object_id = "doems_solar_forecast_remaining_today"' in source
    assert '_attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR' in source


def test_remaining_today_reuses_existing_rolling_future_quarters():
    source = SOLAR_SENSOR.read_text(encoding="utf-8")
    fragment = source.split("class DOEMSSolarForecastRemainingTodaySensor(", 1)[1].split(
        "class DOEMSSolarForecastModelSensor(", 1
    )[0]
    assert "self.manager.energy_for_local_date(today)" in fragment
    assert "dt_util.as_local(dt_util.utcnow()).date()" in fragment
    assert 'self.manager.source_status not in {"ok", "stale"}' in fragment
    assert "return None" in fragment
    forecast = SOLAR_FORECAST.read_text(encoding="utf-8")
    assert "def energy_for_local_date(self, target: date)" in forecast
    assert "for point in points" in forecast
    assert "dt_util.as_local(point.start).date() == target" in forecast
    assert "def points(self)" in forecast


def test_no_planner_or_actuator_changes_are_required():
    source = SOLAR_SENSOR.read_text(encoding="utf-8")
    fragment = source.split("class DOEMSSolarForecastRemainingTodaySensor(", 1)[1].split(
        "class DOEMSSolarForecastModelSensor(", 1
    )[0]
    for forbidden in ("async_call", "services.", "planner", "scheduler", "set_value", "execution_enabled = True"):
        assert forbidden not in fragment
