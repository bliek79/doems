"""Regression contract for the three HA planner source/combined entities."""
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "custom_components/doems/sensor.py").read_text()


def test_three_planner_entities_registered_with_runtime():
    for name in ("Manual", "Automatic", "Combined"):
        assert f"DOEMS{name}PlannerSensor(entry, ems_runtime)" in SOURCE
        assert f'class DOEMS{name}PlannerSensor(_DOEMSEMSRuntimeSensor):' in SOURCE
        assert f'_attr_name = "DOEMS {name} Planner"' in SOURCE
        assert f'_attr_unique_id = "doems_{name.lower()}_planner"' in SOURCE


def test_planner_sources_use_existing_runtime_without_actuation():
    assert 'self.runtime.plan_store.get_plan(slot)' in SOURCE
    assert '(self.runtime.planner_result or {}).get("plan72")' in SOURCE
    assert 'self.runtime.scheduler_result or {}' in SOURCE
    for name in ("Manual", "Automatic", "Combined"):
        part = SOURCE.split(f"class DOEMS{name}PlannerSensor(", 1)[1].split("\nclass ", 1)[0]
        assert 'physical_execution_enabled": False' in part
        assert "async_execute" not in part
        assert "async_stop" not in part
