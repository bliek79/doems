from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_open_meteo_runtime_consumes_foundation_location_and_array_geometry() -> None:
    text = (INTEGRATION / "solar_forecast.py").read_text(encoding="utf-8")
    for token in (
        'snapshot.get("latitude")',
        'snapshot.get("longitude")',
        '"minutely_15": "global_tilted_irradiance"',
        '"forecast_minutely_15": SOLAR_FORECAST_SLOTS + SOLAR_REQUEST_EXTRA_SLOTS',
        '"tilt": float(array["tilt_deg"])',
        'canonical_to_open_meteo_azimuth(float(array["azimuth_deg"]))',
        '"timezone": OPEN_METEO_SOLAR_TIMEZONE',
    ):
        assert token in text
    assert "51.828" not in text
    assert "4.839" not in text


def test_runtime_keeps_last_valid_timeline_on_provider_failure() -> None:
    text = (INTEGRATION / "solar_forecast.py").read_text(encoding="utf-8")
    assert "self._source_points = build_forecast_timeline(" in text
    assert "self.last_error = (" in text
    failure_tail = text.split("self.last_error = (", 1)[1]
    assert "self._source_points = []" not in failure_tail
    assert "SOLAR_RETRY_DELAYS_SECONDS = (0, 5, 15)" in text
    assert "SOLAR_STALE_MINUTES = 90" in text
    assert "SOLAR_EXPIRED_MINUTES = 180" in text


def test_public_solar_sensor_contract_is_doems_prefixed_and_native() -> None:
    text = (INTEGRATION / "solar_sensor.py").read_text(encoding="utf-8")
    for object_id in (
        "doems_solar_source_status",
        "doems_solar_forecast_timeline",
        "doems_solar_forecast_next_quarter",
        "doems_solar_forecast_model",
    ):
        assert object_id in text
    assert 'day not in {"today", "tomorrow"}' in text
    assert 'object_id = f"doems_solar_forecast_{day}_total"' in text
    assert '"slot_count": SOLAR_FORECAST_SLOTS' in text
    assert '"resolution_minutes": SOLAR_RESOLUTION_MINUTES' in text
    assert '"horizon_hours": SOLAR_HORIZON_HOURS' in text
    assert '"points": [point.as_list() for point in points]' in text
    assert '"physical_execution_authority": False' in text


def test_sensor_platform_wires_p31_without_regressing_alpha52_status_fix() -> None:
    text = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    assert "from .solar_forecast import SolarForecastManager" in text
    assert "from .solar_sensor import build_solar_sensors" in text
    assert 'get("solar_forecast")' in text
    assert "entities.extend(build_solar_sensors(entry, solar_forecast))" in text
    assert "and value is not None" in text
    assert 'and value != ""' in text
    assert 'value not in {None, ""}' not in text


def test_foundation_runtime_flag_is_live_but_safety_authority_stays_false() -> None:
    foundation = (INTEGRATION / "solar_foundation.py").read_text(encoding="utf-8")
    binary = (INTEGRATION / "binary_sensor.py").read_text(encoding="utf-8")
    init = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    assert "self.forecast_runtime_active = False" in foundation
    assert '"forecast_runtime_active": self.manager.forecast_runtime_active' in binary
    assert "SolarForecastManager" in init
    assert "await solar_forecast.async_setup()" in init
    assert '"physical_execution_authority": False' in binary
