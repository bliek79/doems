from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_alpha6_version_and_release_material_are_aligned() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    notes = (ROOT / "RELEASE_NOTES_0.1.0-alpha.6.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/p2-energy-forecast-release.yml").read_text(encoding="utf-8")
    assert manifest["version"] == "0.1.0-alpha.6"
    assert 'VERSION = "0.1.0-alpha.6"' in const
    assert "DOEMS 0.1.0-alpha.6 - Solar P3.1 Open-Meteo Runtime" in notes
    assert "gh release create 0.1.0-alpha.6" in workflow
    assert 'title "DOEMS 0.1.0-alpha.6 - Solar P3.1 Open-Meteo Runtime"' in workflow


def test_alpha6_contains_public_solar_runtime_and_dashboard_contract() -> None:
    sensor = (INTEGRATION / "solar_sensor.py").read_text(encoding="utf-8")
    runtime = (INTEGRATION / "solar_forecast.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "examples/solar_p3_1_forecast_card.yaml").read_text(encoding="utf-8")
    for token in (
        "doems_solar_source_status",
        "doems_solar_forecast_timeline",
        "doems_solar_forecast_next_quarter",
        "doems_solar_forecast_model",
    ):
        assert token in sensor
    assert 'object_id = f"doems_solar_forecast_{day}_total"' in sensor
    assert 'OPEN_METEO_SOLAR_ENDPOINT = "https://api.open-meteo.com/v1/forecast"' in runtime
    for entity_id in (
        "sensor.doems_solar_source_status",
        "sensor.doems_solar_forecast_timeline",
        "sensor.doems_solar_forecast_next_quarter",
        "sensor.doems_solar_forecast_today_total",
        "sensor.doems_solar_forecast_tomorrow_total",
        "sensor.doems_solar_forecast_model",
    ):
        assert entity_id in dashboard


def test_alpha6_keeps_safety_and_open_branding_scope_explicit() -> None:
    active_text = "\n".join(path.read_text(encoding="utf-8") for path in INTEGRATION.rglob("*.py"))
    notes = (ROOT / "RELEASE_NOTES_0.1.0-alpha.6.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/p2-energy-forecast-release.yml").read_text(encoding="utf-8")
    assert "async_call(" not in active_text
    assert '"physical_execution_authority": False' in active_text
    assert "branding/icon acceptance issue" in notes
    assert "build_brand_assets.py" not in workflow
