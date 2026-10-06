from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INTEGRATION=ROOT/"custom_components"/"doems"

def _read(name:str)->str: return (INTEGRATION/name).read_text(encoding="utf-8")

def test_three_plan_slots_and_persistent_plan_store_remain() -> None:
    const=_read("const.py"); store=_read("ems_plan_store.py")
    assert "PLAN_SLOT_COUNT = 3" in const
    assert "class DOEMSPlanStore" in store
    assert 'f"{DOMAIN}.{entry_id}.plans"' in store

def test_alpha76_scheduler_priority_and_fixed_soc_contract() -> None:
    scheduler=_read("ems_scheduler.py")
    assert '0 if item.execution_mode == "gepland" else 1' in scheduler
    assert "item.ready_since" in scheduler
    assert "item.slot" in scheduler
    assert '"scheduler_physical_control": False' in scheduler
    assert "5 <= float(target_soc) <= 100" in scheduler
    assert "technical_min_soc_percent" not in scheduler
    assert "max_soc_percent" not in scheduler

def test_manual_plan_entities_still_back_same_plan_store() -> None:
    for name,token in (("select.py","self.plan_store"),("number.py","self.plan_store"),("datetime.py","self.plan_store"),("sensor.py","DOEMSPlanStatusSensor")):
        assert token in _read(name)


def test_manual_plan_edit_clears_stale_derived_commitment_metadata() -> None:
    store=_read("ems_plan_store.py")
    assert 'self._plans[slot]["planned_energy_kwh"] = None' in store
    assert 'self._plans[slot]["planned_end_time"] = None' in store
    assert 'if end is None or end <= start:' in store
    assert 'end = start + timedelta(hours=runtime_h)' in store
