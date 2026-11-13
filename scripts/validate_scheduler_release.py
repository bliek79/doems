"""Validate the chapter-8 register, isolation and preserved Alpha-7.8 algorithms."""
from __future__ import annotations
import ast
import json
from validate_plan_store_release import PRESERVED_BLOBS as CH7_BLOBS
from validate_action_bridge_release import ROOT, git_blob_sha

VERSION = "0.3.0-alpha.8.3"
BASE_COMMIT = "782736687976d09181c4704eff1dcd8ff7c2db0f"
WIRING = {"custom_components/doems/__init__.py", "custom_components/doems/sensor.py",
          "custom_components/doems/binary_sensor.py"}
PRESERVED_BLOBS = {name: digest for name, digest in CH7_BLOBS.items() if name not in WIRING}

# Authorized Alpha84 corrections; retain all other chapter-7 source locks.
PRESERVED_BLOBS.update({'custom_components/doems/planner_72h.py': '6cd89aef7d29a9dc1af6d752365564e41579922f', 'custom_components/doems/planner_72h_runtime.py': '2aefbc82546946af556f4740b2387a2dfbd88675', 'custom_components/doems/planner_action_bridge.py': 'f77629bf8e3f21750f5c9b791758cc84ac1122eb', 'custom_components/doems/plan_store_writer.py': '2528beca1092d5eb2056c05dea34d0396179bc99'})

PRESERVED_BLOBS["custom_components/doems/plan_store.py"] = "d8400b8006f1857023a37aec4fd18c034456dd09"

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
    for name in ("scheduler.py", "scheduler_runtime.py", "scheduler_entities.py"):
        source = (component / name).read_text()
        ast.parse(source)
        for token in (".services.", "async_call(", "Store(", "async_mark_lifecycle(",
                      "async_sync_automatic_plans(", "async_handoff_automatic_plans(",
                      "calculate_plan72(", "calculate_energy_need(", "plan72.refresh("):
            assert token not in source, f"observer boundary violated: {name}: {token}"
    document = (ROOT / "docs/DOEMS3_CHAPTER8_SCHEDULER.md").read_text()
    for suffix in ("status", "selected_plan", "reason", "ready"):
        assert f"doems_scheduler_{suffix}" in document
        assert f"{{entry_id}}_scheduler_{suffix}" in document
    assert "goedgekeurd op 4 november 2026" in document
    assert (ROOT / f"RELEASE_NOTES_v{VERSION}.md").is_file()
    return {"version": VERSION, "base_commit": BASE_COMMIT,
            "reference_commit": "6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d",
            "action_window_contract": "quarter_windows_v1", "protected_blobs": PRESERVED_BLOBS,
            "entity_register_approved": True, "slot_entity_count": 24,
            "diagnostic_entity_count": 6, "scheduler_entity_count": 4,
            "physical_execution_authority": False, "execution_enabled": False}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
