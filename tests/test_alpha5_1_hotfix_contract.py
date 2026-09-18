from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_unitless_number_selectors_do_not_serialize_null_unit() -> None:
    text = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    assert 'if unit is not None:' in text
    assert 'config["unit_of_measurement"] = unit' in text
    assert 'unit_of_measurement=unit' not in text


def test_solar_count_fields_use_unitless_number_helper() -> None:
    text = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    assert 'CONF_SOLAR_INVERTER_GROUP_COUNT' in text
    assert 'CONF_SOLAR_ARRAY_COUNT' in text
    assert '_number(1, SOLAR_MAX_INVERTER_GROUPS, 1)' in text
    assert '_number(1, SOLAR_MAX_ARRAYS, 1)' in text


def test_approved_doems_brand_assets_remain_present() -> None:
    brand = INTEGRATION / "brand"
    expected = {
        "icon.png",
        "icon@2x.png",
        "dark_icon.png",
        "dark_icon@2x.png",
        "logo.png",
        "logo@2x.png",
        "dark_logo.png",
        "dark_logo@2x.png",
    }
    assert {path.name for path in brand.glob("*.png")} == expected



def test_doems_uses_one_complete_brand_logo_for_icon_roles() -> None:
    brand = INTEGRATION / "brand"
    assert (brand / "icon.png").read_bytes() == (brand / "logo.png").read_bytes()
    assert (brand / "icon@2x.png").read_bytes() == (brand / "logo@2x.png").read_bytes()
    assert (brand / "dark_icon.png").read_bytes() == (brand / "dark_logo.png").read_bytes()
    assert (brand / "dark_icon@2x.png").read_bytes() == (brand / "dark_logo@2x.png").read_bytes()

    builder = (ROOT / "scripts" / "build_brand_assets.py").read_text(encoding="utf-8")
    assert ".crop(" not in builder
    assert "DOEMS has one brand logo" in builder
