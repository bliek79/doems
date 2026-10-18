"""R8 shadow must not alter the existing R7/planner implementation."""
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SENSOR = (ROOT / "custom_components/doems/sensor.py").read_text()
SHADOW = (ROOT / "custom_components/doems/r8_shadow.py").read_text()


def test_r8_sensor_registered():
    assert 'doems_r8_shadow_execution' in SENSOR
    assert 'DOEMSR8ShadowSensor(entry, r7_scheduler, manual_plan_store)' in SENSOR


def test_no_physical_control_or_plan_mutation():
    assert "from homeassistant" not in SHADOW
    for forbidden in ("async_call(", "set_plan(", "promote(", "async_create_task(", "async_track_point"):
        assert forbidden not in SHADOW
    assert '"physical_execution_enabled": False' in SHADOW
    assert '"execution_authority": False' in SHADOW


def test_r8_shadow_decision_cases():
    spec = importlib.util.spec_from_file_location("r8_shadow_standalone", ROOT / "custom_components/doems/r8_shadow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluate = module.evaluate_r8_shadow
    base = {"selected_slot": 1, "selected_action": "laden", "selected_origin": "manual",
            "selected_lifecycle": "pending", "safety_status": "safe", "safety_blockers": [],
            "prestart_status": "not_required", "physical_execution_enabled": False,
            "execution_authority": False}
    plan = {"action": "laden", "origin": "manual", "lifecycle_status": "pending",
            "power_w": 300, "target_soc": 80, "max_runtime_h": 1}
    assert evaluate(base, plan)["status"] == "voorbereid_shadow"
    assert evaluate({**base, "selected_slot": None}, plan)["status"] == "geen_actie"
    assert evaluate({**base, "safety_status": "blocked"}, plan)["status"] == "geblokkeerd"
    assert evaluate(base, {**plan, "action": "ontladen"})["status"] == "geblokkeerd"
    assert evaluate(base, {**plan, "lifecycle_status": "verlopen"})["status"] == "geblokkeerd"
    assert evaluate(base, None)["status"] == "geblokkeerd"
    assert evaluate({**base, "execution_authority": True}, plan)["status"] == "geblokkeerd"
