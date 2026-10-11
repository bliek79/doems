from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_solar_actual_quarter_runtime_is_native_and_observer_only() -> None:
    text = (INTEGRATION / "solar_actual.py").read_text(encoding="utf-8")

    for token in (
        "class SolarActualQuarterManager",
        "class SolarQuarterResult",
        "minute=[0, 15, 30, 45]",
        "MIN_VALID_COVERAGE",
        "QUARTER_MINUTES",
        "self._energy_ws",
        "self._covered_seconds",
        "3_600_000",
        "forecast_point_for_start",
        "forecast_locked_at_start",
        "forecast_error_kwh",
        "forecast_absolute_error_kwh",
        "forecast_error_percent",
    ):
        assert token in text

    assert ".services.async_call(" not in text
    assert "select.select_option" not in text
    assert "number.set_value" not in text


def test_solar_actual_quarter_public_sensor_contract_is_doems_native() -> None:
    sensor = (INTEGRATION / "solar_sensor.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    platform = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")

    assert 'doems_solar_actual_quarter' in sensor
    assert 'DOEMS Solar Actual Quarter' in sensor
    assert '"period_start": result.start.isoformat()' in sensor
    assert '"period_end": result.end.isoformat()' in sensor
    assert '"coverage": result.coverage' in sensor
    assert '"measurement_valid": result.measurement_valid' in sensor
    assert '"forecast_kwh": result.forecast_kwh' in sensor
    assert '"forecast_locked_at_start": result.forecast_locked_at_start' in sensor
    assert '"forecast_error_kwh": result.forecast_error_kwh' in sensor
    assert '"forecast_absolute_error_kwh": result.forecast_absolute_error_kwh' in sensor
    assert '"forecast_error_percent": result.forecast_error_percent' in sensor
    assert '"physical_execution_authority": False' in sensor

    assert "SolarActualQuarterManager" in runtime
    assert "await solar_actual.async_setup()" in runtime
    assert '"solar_actual": solar_actual' in runtime
    assert "await solar_actual.async_shutdown()" in runtime

    assert 'get("solar_actual")' in platform
    assert "build_solar_sensors(" in platform


def test_solar_forecast_exposes_exact_cached_slot_without_new_provider_io() -> None:
    text = (INTEGRATION / "solar_forecast.py").read_text(encoding="utf-8")
    method = text.split("def forecast_point_for_start", 1)[1].split(
        "def next_quarter_point", 1
    )[0]

    assert "self._source_points" in method
    assert "dt_util.as_utc" in method
    assert "async_refresh" not in method
    assert "_fetch_array" not in method


def test_solar_actual_quarter_does_not_compare_restart_partial_forecast() -> None:
    text = (INTEGRATION / "solar_actual.py").read_text(encoding="utf-8")

    assert "lock_forecast=False" in text
    assert "lock_forecast=natural_boundary" in text
    assert "comparable_forecast = forecast if self._forecast_locked_at_start else None" in text
