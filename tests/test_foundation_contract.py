from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


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
        "select.py",
        "sensor.py",
        "strings.json",
        "translations/en.json",
        "translations/nl.json",
        "brand/icon.png",
        "brand/icon@2x.png",
        "brand/dark_icon.png",
        "brand/dark_icon@2x.png",
        "brand/logo.png",
        "brand/logo@2x.png",
        "brand/dark_logo.png",
        "brand/dark_logo@2x.png",
    }
    actual = {
        str(path.relative_to(INTEGRATION)).replace("\\", "/")
        for path in INTEGRATION.rglob("*")
        if path.is_file()
    }
    assert required <= actual


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_local_brand_assets_are_valid_pngs() -> None:
    expected = {
        "icon.png": (256, 256),
        "icon@2x.png": (512, 512),
        "dark_icon.png": (256, 256),
        "dark_icon@2x.png": (512, 512),
        "logo.png": (640, 192),
        "logo@2x.png": (1280, 384),
        "dark_logo.png": (640, 192),
        "dark_logo@2x.png": (1280, 384),
    }
    brand = INTEGRATION / "brand"
    assert {path.name for path in brand.glob("*.png")} == set(expected)
    for name, dimensions in expected.items():
        assert _png_dimensions(brand / name) == dimensions
