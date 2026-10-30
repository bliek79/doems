"""Validate the chapter-6 release contract without importing Home Assistant."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.3.0-alpha.6.1"
BASE_COMMIT = "ffafa97c6008bb2ccd5064f346e3a2d6cc0935ad"
PRESERVED_BLOBS = {'custom_components/doems/brand/icon.png': 'fb0dd2dee9b6c7074da8bdde0f5663260677c779', 'custom_components/doems/config_flow.py': '7079e79eca0fe0a53900af47f930c134969ed453', 'custom_components/doems/energy_coordinator.py': 'cae908a072f97b26a9254b3138980f769561171a', 'custom_components/doems/energy_forecast.py': 'd4182ec583840f77525993ab8fc01877a9f91efb', 'custom_components/doems/energy_need.py': 'bc10cbb18dd531735e390fe5369466ab4f466087', 'custom_components/doems/energy_need_runtime.py': '3ab25d81615429f51264beb69d4d0064a34f5863', 'custom_components/doems/energy_sources.py': '7d38e08abd20908d2c274c887e63e180183ada8d', 'custom_components/doems/planner_72h.py': '47dabc7a034476805badd36bba86d72b22341cc2', 'custom_components/doems/planner_72h_runtime.py': '8b7fe10b12b62647f12aaa4b3b111e3e92da34e8', 'custom_components/doems/prices.py': 'bc416175e22a2d7afca87b54b632a45b9c83276f', 'custom_components/doems/prices_model.py': 'a6e69ba26d14be455ce9acc1f874048f9f44b81f', 'custom_components/doems/prices_runtime.py': '61ce175c538e25cc51e0aa79caa437d1bd19172b', 'custom_components/doems/prices_sensor.py': '72b6afb561b4f28f903c78ef91dcad0e3188f18c', 'custom_components/doems/select.py': '7408c52f3764c916447f9124c99a5b92d80f3993', 'custom_components/doems/solar_forecast.py': '667b8f482d9d95d170e20a12af91f3714648717a', 'custom_components/doems/solar_forecast_model.py': 'de704adda34a4a19cf34f10df3c0a5cc05f688ba', 'custom_components/doems/solar_foundation.py': '0eb1d794c80538a1692c49740c3bb6260f2c544c', 'custom_components/doems/solar_foundation_model.py': 'b10b7c28df6f93057bab958b510706dc538a2c49', 'custom_components/doems/solar_sensor.py': 'b309eeaf97ce5dd0865123ee618385b4c09ff315', 'custom_components/doems/strings.json': '7069cc74ec207bc1bcab6fb8b212679c9309320a', 'custom_components/doems/translations/en.json': '7069cc74ec207bc1bcab6fb8b212679c9309320a', 'custom_components/doems/translations/nl.json': 'a02037dee5d3773c0b811a57370cb7542974061d'}


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def validate() -> dict:
    component = ROOT / "custom_components/doems"
    manifest = json.loads((component / "manifest.json").read_text())
    constants = ast.parse((component / "const.py").read_text())
    version = next(ast.literal_eval(node.value) for node in constants.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets))
    assert manifest["version"] == version == VERSION, "public version mismatch"
    assert manifest["domain"] == "doems" and manifest["requirements"] == []
    for path in component.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    for name, expected in PRESERVED_BLOBS.items():
        assert git_blob_sha((ROOT / name).read_bytes()) == expected, f"protected Alpha 5.3 source changed: {name}"
    for name in ("planner_72h.py", "planner_72h_runtime.py"):
        source = (component / name).read_text()
        ast.parse(source)
        assert ".services." not in source, f"physical service surface in {name}"
    assert "practical_windows=True" in (component / "planner_72h_runtime.py").read_text()
    for name in ("planner_action_bridge.py", "planner_action_bridge_runtime.py"):
        source = (component / name).read_text()
        ast.parse(source)
        for token in (".services.", "async_call(", "Store(", "calculate_plan72(", "calculate_energy_need("):
            assert token not in source, f"observer boundary violated: {name}: {token}"
    assert "action_bridge" in (component / "__init__.py").read_text()
    assert (ROOT / f"RELEASE_NOTES_v{VERSION}.md").is_file()
    assert (ROOT / "docs/DOEMS3_CHAPTER6_ACTION_BRIDGE.md").is_file()
    assert (ROOT / "examples/action_bridge_validation_card.yaml").is_file()
    return {"version": VERSION, "base_commit": BASE_COMMIT, "action_window_contract": "quarter_windows_v1", "protected_blobs": PRESERVED_BLOBS}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
