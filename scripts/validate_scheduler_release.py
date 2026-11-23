"""Validate the chapter-8 register, isolation and preserved Alpha-7.8 algorithms."""
from __future__ import annotations
import ast
import json
from validate_plan_store_release import PRESERVED_BLOBS as CH7_BLOBS
from validate_action_bridge_release import ROOT, git_blob_sha

VERSION = "0.3.0-alpha.8.10"
BASE_COMMIT = "95cc001d99b5951a02ca199dcbc34f13a7ff17d2"
WIRING = {"custom_components/doems/__init__.py", "custom_components/doems/sensor.py",
          "custom_components/doems/binary_sensor.py"}
PRESERVED_BLOBS = {name: digest for name, digest in CH7_BLOBS.items() if name not in WIRING}

# Reviewed H8 Alpha84 strategy migration and Alpha 8.6 native safety repair.\n# All other source locks retain their immutable prior baselines.
# Prior published Alpha 8.4 hashes remain recorded in docs/H8_SOURCE_HASH_REVIEW_20261116.md.
PRESERVED_BLOBS.update({'custom_components/doems/planner_72h.py': '751ae0ac98b454c6f7290700a2d783e571ae7c51', 'custom_components/doems/planner_72h_runtime.py': 'f9a23be93ad239c9a17fb58fd619ca9628688c80', 'custom_components/doems/planner_action_bridge.py': '79cfbc8053710e0108f02407811fcea083f39df1', 'custom_components/doems/plan_store_writer.py': '44b6cda5e07f04957f4958d3ef08df92ec29e037'})

# Alpha 8.8 review: only the public, read-only Solar sensor registration changes.
# Keep every other inherited protected source hash unchanged.
PRESERVED_BLOBS["custom_components/doems/solar_sensor.py"] = "4c2ec74d780d36db7fa5f38327d0582a4e7d2f59"

PRESERVED_BLOBS["custom_components/doems/alpha84_planning.py"] = "e80b5a3c31cf95711384ebc6f81f5d82bbc861bf"  # Reviewed 15m contiguous source only; frozen hourly parity retained.
# H5.2 reviewed Alpha84 source handoff: keep original hourly oracle unchanged.
PRESERVED_BLOBS["custom_components/doems/alpha84_bundle.py"] = "a60cadbf242b70c6c275bfc66bf03dd99aec3d3c"
PRESERVED_BLOBS["custom_components/doems/alpha84_action_bridge.py"] = "abf789e567c0f98424d927e94cfc9d6eed425f02"
PRESERVED_BLOBS["custom_components/doems/plan_store.py"] = "b6dfec3b0b5a2070167a7d107acaa6320a76c6a8"
PRESERVED_BLOBS["custom_components/doems/plan_store_adapter.py"] = "d4b4ae38cd309c5cb8538e89477cfb941da580d7"

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
    # H5.4: verify the *production* HA worker is wired to exactly the
    # frozen Alpha84 strategy owner. Historical native optimisers exist for
    # their old isolated regression tests but cannot be silently enabled in
    # the Home Assistant control chain.
    worker_ast = ast.parse((component / "planner_72h_runtime.py").read_text())
    evaluate = next((n for n in worker_ast.body
        if isinstance(n, ast.FunctionDef) and n.name == "_evaluate"), None)
    assert evaluate is not None, "H5.4 missing production worker"
    strategy_calls = [n for n in ast.walk(evaluate)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "calculate_plan72"]
    assert len(strategy_calls) == 1, "H5.4 ambiguous production strategy"
    arguments = {arg.arg: arg.value for arg in strategy_calls[0].keywords}
    assert isinstance(arguments.get("practical_windows"), ast.Constant)
    assert arguments["practical_windows"].value is True
    # H5.4: both approved Chapter 7 files remain byte-identical; the
    # integration setup checks the source factory before ANY HA subscriptions.
    setup_source = (component / "__init__.py").read_text()
    assert "original_alpha84_owner_present(" in setup_source
    assert "entry.options.get(CONF_PLAN72_ENABLED, False)" in setup_source
    assert setup_source.index("not original_alpha84_owner_present(") < (
        setup_source.index("await _async_remove_legacy_solar_freeze_storage(hass)"))
    assert (component / "alpha84_strategy_guard.py").is_file()
    assert isinstance(arguments.get("strategy_factory"), ast.Name)
    assert arguments["strategy_factory"].id == "compute_strategy_bundle", (
        "H5.4 original Alpha84 strategy not bound")
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
