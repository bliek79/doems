"""Validate the chapter-5 release contract without importing Home Assistant."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.3.0-alpha.5.3"
BASE_COMMIT = "af6a893fe2b85003d030525e9f60ee031fa800ce"
PRESERVED_BLOBS = {'custom_components/doems/__init__.py': '25a86b36f84516c49671aab9189fa789ade9e460', 'custom_components/doems/binary_sensor.py': '25de66c9bea961fbfda5a147250fe579b6cc3042', 'custom_components/doems/brand/icon.png': 'fb0dd2dee9b6c7074da8bdde0f5663260677c779', 'custom_components/doems/config_flow.py': '7079e79eca0fe0a53900af47f930c134969ed453', 'custom_components/doems/energy_coordinator.py': 'cae908a072f97b26a9254b3138980f769561171a', 'custom_components/doems/energy_forecast.py': 'd4182ec583840f77525993ab8fc01877a9f91efb', 'custom_components/doems/energy_need.py': 'bc10cbb18dd531735e390fe5369466ab4f466087', 'custom_components/doems/energy_need_runtime.py': '3ab25d81615429f51264beb69d4d0064a34f5863', 'custom_components/doems/energy_sources.py': '7d38e08abd20908d2c274c887e63e180183ada8d', 'custom_components/doems/prices.py': 'bc416175e22a2d7afca87b54b632a45b9c83276f', 'custom_components/doems/prices_model.py': 'a6e69ba26d14be455ce9acc1f874048f9f44b81f', 'custom_components/doems/prices_runtime.py': '61ce175c538e25cc51e0aa79caa437d1bd19172b', 'custom_components/doems/prices_sensor.py': '72b6afb561b4f28f903c78ef91dcad0e3188f18c', 'custom_components/doems/select.py': '7408c52f3764c916447f9124c99a5b92d80f3993', 'custom_components/doems/sensor.py': '760e6bdc8cd2a7adf498a6ec888f7a95c9140b84', 'custom_components/doems/solar_forecast.py': '667b8f482d9d95d170e20a12af91f3714648717a', 'custom_components/doems/solar_forecast_model.py': 'de704adda34a4a19cf34f10df3c0a5cc05f688ba', 'custom_components/doems/solar_foundation.py': '0eb1d794c80538a1692c49740c3bb6260f2c544c', 'custom_components/doems/solar_foundation_model.py': 'b10b7c28df6f93057bab958b510706dc538a2c49', 'custom_components/doems/solar_sensor.py': 'b309eeaf97ce5dd0865123ee618385b4c09ff315', 'custom_components/doems/strings.json': '7069cc74ec207bc1bcab6fb8b212679c9309320a', 'custom_components/doems/translations/en.json': '7069cc74ec207bc1bcab6fb8b212679c9309320a', 'custom_components/doems/translations/nl.json': 'a02037dee5d3773c0b811a57370cb7542974061d'}


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
        assert git_blob_sha((ROOT / name).read_bytes()) == expected, f"protected Alpha 4.3 source changed: {name}"
    for name in ("planner_72h.py", "planner_72h_runtime.py"):
        source = (component / name).read_text()
        ast.parse(source)
        assert ".services." not in source, f"physical service surface in {name}"
    assert "practical_windows=True" in (component / "planner_72h_runtime.py").read_text()
    assert not (component / "planner_action_bridge.py").exists(), "chapter6 must not leak into chapter5"
    assert (ROOT / f"RELEASE_NOTES_v{VERSION}.md").is_file()
    assert (ROOT / "docs/DOEMS3_CHAPTER5_PLAN72.md").is_file()
    assert (ROOT / "examples/plan72_validation_card.yaml").is_file()
    return {"version": VERSION, "base_commit": BASE_COMMIT, "action_window_contract": "quarter_windows_v1", "protected_blobs": PRESERVED_BLOBS}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
