from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_alpha7_version_release_and_prices_assets_are_aligned() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    notes = (ROOT / "RELEASE_NOTES_0.1.0-alpha.7.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/p2-energy-forecast-release.yml").read_text(encoding="utf-8")
    assert manifest["version"] == "0.1.0-alpha.7"
    assert 'VERSION = "0.1.0-alpha.7"' in const
    assert "DOEMS 0.1.0-alpha.7 - Prices P4.1 Runtime" in notes
    assert "gh release create 0.1.0-alpha.7" in workflow
    assert (INTEGRATION / "prices.py").is_file()
    assert (INTEGRATION / "prices_model.py").is_file()


def test_prices_install_contract_is_third_party_ready() -> None:
    config = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    for token in (
        "prices_enabled",
        "price_resolution_preference",
        "tariff_profile_id",
        "tariff_supplier",
        "tariff_valid_from",
        "vat_percent",
        "electricity_import_supplier_incl_vat",
        "electricity_import_tax_incl_vat",
        "electricity_export_supplier_incl_vat",
        "electricity_export_tax_incl_vat",
        "gas_prices_enabled",
        "gas_market_entity",
    ):
        assert token in config or token in const
    assert "ANWB Energie" not in config
    assert "sensor.energyzero" not in config


def test_public_prices_contract_and_native_timeline_are_explicit() -> None:
    runtime = (INTEGRATION / "prices.py").read_text(encoding="utf-8")
    model = (INTEGRATION / "prices_model.py").read_text(encoding="utf-8")
    for entity in (
        "sensor.doems_prices_status",
        "sensor.doems_prices_market_current",
        "sensor.doems_prices_import_current",
        "sensor.doems_prices_export_current",
        "sensor.doems_prices_timeline",
        "sensor.doems_prices_tariff_profile",
    ):
        assert entity in runtime
    assert '"physical_execution_authority": False' in runtime
    assert "PRICE_BUFFER_HOURS = 76" in model
    assert "FORECAST_HORIZON_HOURS = 72" in model
    assert "FORECAST_SLOTS = FORECAST_HORIZON_HOURS * 60 // QUARTER_MINUTES" in model
    assert '"kind": "missing"' in runtime
    assert '"valid": False' in runtime


def test_prices_dashboard_has_exactly_import_and_export_primary_series() -> None:
    card = (ROOT / "examples/prices_p4_1_forecast_card.yaml").read_text(encoding="utf-8")
    assert card.count("entity: sensor.doems_prices_timeline") == 2
    assert "name: Import all-in" in card
    assert "name: Export all-in" in card
    assert "name: Market" not in card
    assert "p.import_all_in" in card
    assert "p.export_all_in" in card
