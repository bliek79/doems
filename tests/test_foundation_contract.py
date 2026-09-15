from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"

FORBIDDEN_ACTIVE_IDENTITIES = (
    "dummy_os_data",
    "Dummy OS Data",
    "dummy_os_energy",
    "Dummy OS Energy",
)


def test_manifest_contract() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "doems"
    assert manifest["name"] == "DOEMS"
    assert manifest["version"] == "0.1.0-alpha.1"
    assert manifest["config_flow"] is True
    assert manifest["single_config_entry"] is True


def test_required_foundation_files_exist() -> None:
    required = {
        "__init__.py",
        "config_flow.py",
        "const.py",
        "manifest.json",
        "sensor.py",
        "strings.json",
        "translations/en.json",
        "translations/nl.json",
    }
    actual = {
        str(path.relative_to(INTEGRATION)).replace("\\", "/")
        for path in INTEGRATION.rglob("*")
        if path.is_file()
    }
    assert required <= actual


def test_active_integration_identity_is_pure() -> None:
    for path in INTEGRATION.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".json", ".yaml", ".yml"}:
            continue
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_ACTIVE_IDENTITIES:
            assert forbidden not in text, f"{forbidden!r} found in {path}"


def test_step0_requires_no_functional_installation_input() -> None:
    config_flow = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    assert "data_schema=vol.Schema({})" in config_flow
    assert "data={}" in config_flow


def test_step0_has_no_physical_control_surface() -> None:
    active_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in INTEGRATION.rglob("*.py")
    )
    assert "async_call(" not in active_text
    assert '"physical_execution_authority": False' in active_text
