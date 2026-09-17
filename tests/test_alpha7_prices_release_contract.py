from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alpha7_versions_and_prices_files():
    const = (ROOT / "custom_components/doems/const.py").read_text()
    manifest = (ROOT / "custom_components/doems/manifest.json").read_text()
    init = (ROOT / "custom_components/doems/__init__.py").read_text()
    prices = (ROOT / "custom_components/doems/prices.py").read_text()
    example = (ROOT / "examples/prices_p4_forecast_card.yaml").read_text()
    assert 'VERSION = "0.1.0-alpha.7"' in const
    assert '"version": "0.1.0-alpha.7"' in manifest
    assert "DOEMSPricesManager" in init
    for entity in (
        "sensor.doems_prices_status",
        "sensor.doems_prices_market_current",
        "sensor.doems_prices_import_current",
        "sensor.doems_prices_export_current",
        "sensor.doems_prices_timeline",
        "sensor.doems_prices_tariff_profile",
    ):
        assert entity in prices
    assert "import_all_in" in example
    assert "export_all_in" in example
    assert example.count("type: line") == 2
