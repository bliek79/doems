from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_alpha6_release_material_is_preserved_as_history() -> None:
    notes = (ROOT / "RELEASE_NOTES_0.1.0-alpha.6.md").read_text(encoding="utf-8")
    assert "DOEMS 0.1.0-alpha.6 - Solar P3.1 Open-Meteo Runtime" in notes


def test_alpha6_public_solar_runtime_contract_is_carried_forward() -> None:
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


def test_safety_and_branding_scope_remain_explicit() -> None:
    active_text = "\n".join(path.read_text(encoding="utf-8") for path in INTEGRATION.rglob("*.py"))
    workflow = (ROOT / ".github/workflows/p2-energy-forecast-release.yml").read_text(encoding="utf-8")
    assert active_text.count(".services.async_call(") == 1
    prices = (INTEGRATION / "prices.py").read_text(encoding="utf-8")
    assert '"energyzero"' in prices and '"get_gas_prices"' in prices
    assert '"physical_execution_authority": False' in active_text
    # Alpha7.5 is the explicitly authorized branding-only release. The
    # builder may run only as a deterministic validation step; safety/runtime
    # semantics remain unchanged.
    assert "python scripts/build_brand_assets.py" in workflow
    assert "git diff --exit-code -- custom_components/doems/brand" in workflow
