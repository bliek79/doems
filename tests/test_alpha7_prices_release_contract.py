from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alpha7_1_versions_and_prices_files():
    const = (ROOT / "custom_components/doems/const.py").read_text()
    manifest = (ROOT / "custom_components/doems/manifest.json").read_text()
    init = (ROOT / "custom_components/doems/__init__.py").read_text()
    prices = (ROOT / "custom_components/doems/prices.py").read_text()
    config_flow = (ROOT / "custom_components/doems/config_flow.py").read_text()
    example = (ROOT / "examples/prices_p4_forecast_card.yaml").read_text()
    assert 'VERSION = "0.1.0-alpha.7.1"' in const
    assert '"version": "0.1.0-alpha.7.1"' in manifest
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

    # Home Assistant NumberSelector requires step >= 0.001 unless step='any'.
    # High precision tariff/location fields therefore must use the supported
    # free precision mode, otherwise the Prices form fails to render.
    assert "0.00001" not in config_flow
    assert "0.000001" not in config_flow
    assert 'Literal["any"]' in config_flow

    # Finishing the last configured Solar array must not advance the cursor
    # beyond the configured array count while transitioning to Prices.
    assert "if index + 1 < count:" in config_flow
    assert "self._solar_array_index += 1" not in config_flow
    assert '"array 3 of 2"' in config_flow
