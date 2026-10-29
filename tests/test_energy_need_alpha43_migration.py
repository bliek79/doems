from pathlib import Path
R=Path(__file__).resolve().parents[1]/"custom_components"/"doems"
def test_missing_new_options_cannot_crash_registration():
    code=(R/"energy_need_runtime.py").read_text()
    assert "self.entry.options.get(key)" in code
    assert "source_entities = [entity_id for entity_id in source_entities if entity_id]" in code
    assert "if source_entities:" in code
    assert "capacity_state.state if capacity_state is not None else None" in code
    assert "minimum_state.state if minimum_state is not None else None" in code
