from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"
APPROVED_BRAND_BLOB_SHA = "fb0dd2dee9b6c7074da8bdde0f5663260677c779"
APPROVED_BRAND_SIZE = 1864695


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


def test_doems_uses_exact_existing_dummy_os_brand_icon() -> None:
    brand = INTEGRATION / "brand"
    files = [path.name for path in brand.iterdir() if path.is_file()]
    assert files == ["icon.png"]
    icon = brand / "icon.png"
    data = icon.read_bytes()
    assert len(data) == APPROVED_BRAND_SIZE
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    git_blob_sha = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    assert git_blob_sha == APPROVED_BRAND_BLOB_SHA
