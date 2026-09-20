from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"
APPROVED_BRAND_BLOB_SHA = "fb0dd2dee9b6c7074da8bdde0f5663260677c779"


def test_foundation_still_installs_without_component_input() -> None:
    config_flow = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    assert "data_schema=vol.Schema({})" in config_flow
    assert "data={}" in config_flow


def test_required_p2_files_exist() -> None:
    required = {
        "__init__.py",
        "config_flow.py",
        "const.py",
        "energy_coordinator.py",
        "energy_forecast.py",
        "energy_sources.py",
        "manifest.json",
        "presence.py",
        "ems_settings.py",
        "select.py",
        "switch.py",
        "datetime.py",
        "binary_sensor.py",
        "sensor.py",
        "strings.json",
        "translations/en.json",
        "translations/nl.json",
        "brand/icon.png",
    }
    actual = {
        str(path.relative_to(INTEGRATION)).replace("\\", "/")
        for path in INTEGRATION.rglob("*")
        if path.is_file()
    }
    assert required <= actual


def test_local_brand_is_exact_existing_dummy_os_icon() -> None:
    brand = INTEGRATION / "brand"
    assert {path.name for path in brand.iterdir() if path.is_file()} == {"icon.png"}
    icon = brand / "icon.png"
    data = icon.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) == 1864695
    git_blob_sha = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    assert git_blob_sha == APPROVED_BRAND_BLOB_SHA
