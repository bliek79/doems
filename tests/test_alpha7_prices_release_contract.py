from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alpha7_8_versions_prices_files_and_registered_entities():
    const = (ROOT / "custom_components/doems/const.py").read_text()
    manifest = (ROOT / "custom_components/doems/manifest.json").read_text()
    init = (ROOT / "custom_components/doems/__init__.py").read_text()
    sensor = (ROOT / "custom_components/doems/sensor.py").read_text()
    prices = (ROOT / "custom_components/doems/prices.py").read_text()
    prices_sensor = (ROOT / "custom_components/doems/prices_sensor.py").read_text()
    prices_runtime = (ROOT / "custom_components/doems/prices_runtime.py").read_text()
    config_flow = (ROOT / "custom_components/doems/config_flow.py").read_text()
    example = (ROOT / "examples/prices_p4_forecast_card.yaml").read_text()

    assert 'VERSION = "0.1.0-alpha.7.23"' in const
    assert '"version": "0.1.0-alpha.7.23"' in manifest
    assert "DOEMSRegisteredPricesManager" in init
    assert "build_prices_sensors" in sensor
    assert 'entry_data.get("prices")' in sensor

    for object_id in (
        "doems_prices_status",
        "doems_prices_market_current",
        "doems_prices_import_current",
        "doems_prices_export_current",
        "doems_prices_timeline",
        "doems_prices_tariff_profile",
        "doems_prices_gas_market",
        "doems_prices_gas_all_in",
        "doems_prices_gas_vs_electricity",
    ):
        assert object_id in prices_sensor

    # Runtime ownership is now the SensorEntity platform. The Alpha7/7.1
    # direct-state publisher remains only in the legacy base implementation
    # and is suppressed by the actual Alpha7.8 runtime manager.
    assert "class DOEMSRegisteredPricesManager" in prices_runtime
    assert "def _publish_states(self) -> None:" in prices_runtime
    assert "SensorEntity owns public state output" in prices_runtime
    assert "async_remove" not in prices_runtime

    # Existing Prices P4 data semantics remain present.
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

    # Alpha7.4 makes gas source semantics explicit rather than trusting a
    # provider label or subtracting tariff components heuristically.
    for token in (
        "gas_source_mode",
        "energyzero_market_action",
        "gas_energyzero_config_entry",
        "energyzero.get_gas_prices",
        "market_incl_vat",
        "return_response=True",
    ):
        assert token in (const + config_flow + prices + prices_sensor)
    assert '"incl_vat": True' in prices
    assert "- self.gas_variable_addon" not in prices
    assert "unsupported_gas_price_unit" in config_flow

    # Alpha7.4 adds exactly one read-only gas/electricity comparison sensor.
    assert "GAS_HIGHER_HEATING_VALUE_KWH_M3 = 9.77" in const
    assert "gas_equivalent_price_eur_kwh" in prices
    assert "electricity_to_gas_ratio" in prices
    assert "DOEMSPricesGasVsElectricitySensor" in prices_sensor
    assert "energy_carrier_price_only" in prices
    assert "efficiency_or_cop_included" in prices

    # Home Assistant NumberSelector requires step >= 0.001 unless step='any'.
    assert "0.00001" not in config_flow
    assert "0.000001" not in config_flow
    assert 'Literal["any"]' in config_flow

    # Finishing the last configured Solar array must not advance the cursor
    # beyond the configured array count while transitioning to Prices.
    assert "if index + 1 < count:" in config_flow
    assert "self._solar_array_index += 1" not in config_flow
    assert '"array 3 of 2"' in config_flow





def test_alpha7_8_preserves_prices_and_brand_contract():
    brand = ROOT / "custom_components/doems/brand"
    assert {p.name for p in brand.iterdir() if p.is_file()} == {"icon.png"}
    assert not (ROOT / "scripts/build_brand_assets.py").exists()
