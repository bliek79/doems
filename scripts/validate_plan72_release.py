"""Validate the chapter-5 release contract without importing Home Assistant."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.3.0-alpha.5.1"
BASE_COMMIT = "75516b5aa99282b03b91c1f5b534c02b7b07ce82"
PRESERVED_BLOBS = {
    "custom_components/doems/brand/icon.png": "fb0dd2dee9b6c7074da8bdde0f5663260677c779",
    "custom_components/doems/energy_need.py": "bc10cbb18dd531735e390fe5369466ab4f466087",
    "custom_components/doems/energy_need_runtime.py": "3ab25d81615429f51264beb69d4d0064a34f5863",
}


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
    assert (ROOT / f"RELEASE_NOTES_v{VERSION}.md").is_file()
    assert (ROOT / "docs/DOEMS3_CHAPTER5_PLAN72.md").is_file()
    assert (ROOT / "examples/plan72_validation_card.yaml").is_file()
    return {"version": VERSION, "base_commit": BASE_COMMIT, "protected_blobs": PRESERVED_BLOBS}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
