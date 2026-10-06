from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _load(name: str):
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    return importlib.import_module(f"custom_components.doems.{name}")


def test_alpha3_manual_plan_defaults_match_proven_reference() -> None:
    m = _load("manual_plan_model")
    plan = m.new_manual_plan()
    assert plan == {
        "action": "geen",
        "execution_mode": "direct",
        "start_time": None,
        "power_w": 100.0,
        "target_soc": 80.0,
        "max_runtime_h": 2.0,
        "max_start_delay_min": 15.0,
        "lifecycle_status": "concept",
        "lifecycle_reason": None,
        "lifecycle_updated_at": None,
        "origin": "manual",
    }
    assert m.PLAN_SLOT_COUNT == 3


def test_alpha3_manual_plan_ranges_match_july_contract() -> None:
    m = _load("manual_plan_model")
    now = datetime(2026, 10, 6, 18, 0, tzinfo=timezone.utc)
    plan = m.new_manual_plan()
    plan.update(
        {
            "action": "laden",
            "execution_mode": "gepland",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "power_w": 3500,
            "target_soc": 100,
            "max_runtime_h": 0.5,
            "max_start_delay_min": 120,
        }
    )
    assert m.validate_manual_plan(plan, now=now) == []

    plan["max_runtime_h"] = 0.49
    assert "max_runtime_out_of_range" in m.validate_manual_plan(plan, now=now)
    plan["max_runtime_h"] = 12.01
    assert "max_runtime_out_of_range" in m.validate_manual_plan(plan, now=now)


def test_alpha3_schedule_requires_valid_future_start() -> None:
    m = _load("manual_plan_model")
    now = datetime(2026, 10, 6, 18, 0, tzinfo=timezone.utc)
    plan = m.new_manual_plan()
    plan.update(
        {
            "action": "ontladen",
            "execution_mode": "gepland",
            "power_w": 1000,
            "target_soc": 20,
            "max_runtime_h": 2,
            "max_start_delay_min": 15,
        }
    )
    assert "start_time_required" in m.validate_manual_plan(
        plan, now=now, require_future_start=True
    )
    plan["start_time"] = (now - timedelta(minutes=1)).isoformat()
    assert "start_time_not_future" in m.validate_manual_plan(
        plan, now=now, require_future_start=True
    )


def test_alpha3_status_is_manual_only_and_no_scheduler_semantics() -> None:
    m = _load("manual_plan_model")
    now = datetime(2026, 10, 6, 18, 0, tzinfo=timezone.utc)
    plan = m.new_manual_plan()
    assert m.manual_plan_status(plan, now=now) == "leeg"

    plan.update(
        {
            "action": "laden",
            "execution_mode": "gepland",
            "start_time": (now + timedelta(hours=1)).isoformat(),
        }
    )
    assert m.manual_plan_status(plan, now=now) == "concept"
    plan["lifecycle_status"] = "pending"
    assert m.manual_plan_status(plan, now=now) == "gepland"
    plan["lifecycle_status"] = "geannuleerd"
    assert m.manual_plan_status(plan, now=now) == "geannuleerd"


def test_alpha3_public_entity_identity_reuses_existing_doems_plan_ids() -> None:
    select = (INTEGRATION / "select.py").read_text(encoding="utf-8")
    number = (INTEGRATION / "number.py").read_text(encoding="utf-8")
    dt = (INTEGRATION / "datetime.py").read_text(encoding="utf-8")
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")

    assert 'f"doems_plan_{slot}_{field}"' in select
    assert 'f"doems_plan_{slot}_{definition.object_suffix}"' in number
    assert 'f"doems_plan_{slot}_start_time"' in dt
    assert 'f"doems_plan_{slot}_status"' in sensor


def test_alpha3_store_is_persistent_manual_only_and_execution_free() -> None:
    store = (INTEGRATION / "manual_plan_store.py").read_text(encoding="utf-8")
    services = (INTEGRATION / "manual_plan_services.py").read_text(encoding="utf-8")
    init = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")

    assert "doems.{entry_id}.manual_plans" in store
    assert '"origin"] = "manual"' in store
    assert "DOEMSManualPlanStore" in init
    assert "async_register_manual_plan_services" in init
    assert '"number"' in const and '"datetime"' in const

    assert "async_call(" not in store
    assert "async_call(" not in services
    assert "third_party_control" not in store + services
    assert "automatic_72h_planner" not in store + services
    assert "scheduler" not in store.lower()
    assert "soc_projection_active" in (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    assert '"physical_execution_authority": False' in (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
