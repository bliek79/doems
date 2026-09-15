from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_foundation_still_installs_without_component_input() -> None:
    config_flow = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    assert "data_schema=vol.Schema({})" in config_flow
    assert "data={}" in config_flow


def test_required_p2_files_exist() -> None:
    required = {"__init__.py", "config_flow.py", "const.py", "energy_coordinator.py", "energy_forecast.py", "energy_sources.py", "manifest.json", "select.py", "sensor.py", "strings.json", "translations/en.json", "translations/nl.json"}
    actual = {str(path.relative_to(INTEGRATION)).replace("\\", "/") for path in INTEGRATION.rglob("*") if path.is_file()}
    assert required <= actual
