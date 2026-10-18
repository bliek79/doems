"""R8-A sensor runtime wiring and fail-closed contract."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENSOR = (ROOT / "custom_components/doems/sensor.py").read_text()
VALIDATOR = (ROOT / "custom_components/doems/ems_execution_readiness.py").read_text()


def test_sensor_registered_on_existing_r7_and_store():
    assert "entities.append(DOEMSR8AReadinessSensor(entry, r7_scheduler, manual_plan_store))" in SENSOR
    assert 'doems_r8a_execution_readiness' in SENSOR


def test_sensor_subscribes_without_mutating_r7():
    cls = SENSOR.split("class DOEMSR8AReadinessSensor(SensorEntity):", 1)[1]
    assert "self.scheduler.async_add_listener(self._handle_update)" in cls
    assert "self.store.get_plan(slot)" in cls
    for forbidden in ("async_promote_automatic_plan", "async_call(", "async_set_plan", "async_create_task", "async_track_point_in_utc_time"):
        assert forbidden not in cls


def test_evidence_missing_fail_closed():
    cls = SENSOR.split("class DOEMSR8AReadinessSensor(SensorEntity):", 1)[1]
    assert "controller_conflict=None" in cls
    assert "final_revalidation_safe=None" in cls
    assert "handoff_ready=None" in cls
    assert "atomic_plan_revision_match=None" in cls
    assert '"technical_ready": False' in cls
    assert '"execution_authorized": False' in cls
    assert '"native_slot_count": 288' in cls


def test_validator_no_physical_authority():
    assert '"execution_authorized": False' in VALIDATOR
    assert '"execution_performed": False' in VALIDATOR
    assert "from homeassistant" not in VALIDATOR
