"""Validate the approved chapter-7 release boundary without importing HA."""
from __future__ import annotations
import ast
import json
from validate_action_bridge_release import ROOT, PRESERVED_BLOBS as ALPHA6_BLOBS, git_blob_sha

VERSION = "0.3.0-alpha.7.2"
BASE_COMMIT = "3e858afb90770bdaaf8c180f18024da6789bae38"
REVIEWED_CH7_BLOBS = {'custom_components/doems/planner_72h.py': '1835ae08a0d47decf32373cf02afbf194227cec3', 'custom_components/doems/planner_72h_runtime.py': 'eeabe8a7455984ecaa9dba704f027b2f6fd41d95', 'custom_components/doems/select.py': '990b7c1a4df89249adcb0dd8e7b221ee1cb5dd29', 'custom_components/doems/__init__.py': '9d5ff3c5c1d4de54c6089ad907e9f329ae4ef22b', 'custom_components/doems/plan_store.py': '602d1ee3e4aaf12e2ccaa9c94946ae3946de1cee', 'custom_components/doems/plan_store_writer.py': '3da96e5a0034de0d502b990c85a20b2b41f21755', 'custom_components/doems/plan_store_adapter.py': '6a4f429f432c7771803dde65d16ebf4f414c7b52', 'custom_components/doems/plan_slot_assignment.py': '43c0b8ceabae3921c5b28bd4ff89a2e056326557', 'custom_components/doems/plan_slot_entities.py': '3a8ee4f993b9d02bb740b2745476f2e5518dfa3b', 'custom_components/doems/plan_store_services.py': '746cb5fa419118b242d339e992b49254c7b8ec6a', 'custom_components/doems/number.py': '2f306d1551e5d8af35d0bd79e2e2d6416db7ae96', 'custom_components/doems/datetime.py': '9a4b8dea303737e9350e0c33081a00bbdd58e806', 'custom_components/doems/services.yaml': 'e4c95ae6cde67168b29868132fb98bbb555a752a'}
PRESERVED_BLOBS = {**ALPHA6_BLOBS, **REVIEWED_CH7_BLOBS}


def validate():
    component = ROOT / "custom_components/doems"
    manifest = json.loads((component / "manifest.json").read_text())
    constants = ast.parse((component / "const.py").read_text())
    version = next(ast.literal_eval(n.value) for n in constants.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets))
    assert manifest["version"] == version == VERSION, "public version mismatch"
    assert manifest["domain"] == "doems" and manifest["requirements"] == []
    for path in component.rglob("*.json"):
        json.loads(path.read_text())
    for path, expected in PRESERVED_BLOBS.items():
        assert git_blob_sha((ROOT / path).read_bytes()) == expected, f"reviewed source changed: {path}"
    document = (ROOT / "docs/DOEMS3_CHAPTER7_PLAN_STORE.md").read_text()
    assert "entiteitenregister door de gebruiker goedgekeurd op 30 oktober 2026" in document
    assert (ROOT / f"RELEASE_NOTES_v{VERSION}.md").is_file()
    return {"version": VERSION, "base_commit": BASE_COMMIT,
            "action_window_contract": "quarter_windows_v1", "protected_blobs": PRESERVED_BLOBS,
            "entity_register_approved": True, "slot_entity_count": 24, "diagnostic_entity_count": 6}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
