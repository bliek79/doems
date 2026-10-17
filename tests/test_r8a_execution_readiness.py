"""R8-A v2 regression boundary: pure observer of R7."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("r8a", Path(__file__).resolve().parents[1] / "custom_components/doems/ems_execution_readiness.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
validate = module.validate_execution_readiness


def case(origin="manual", mode="gepland"):
    start = "2026-10-17T14:00:00+00:00"
    plan = dict(slot=2, origin=origin, execution_mode=mode, lifecycle_status="pending",
                action="laden", lifecycle_updated_at=start, start_time=start,
                max_start_delay_min=15, power_w=1000, target_soc=90, max_runtime_h=2)
    if origin == "automatic_72h_planner":
        plan["planner_identity"] = "auto-123"
    r7 = dict(selected_slot=2, selected_action="laden", selected_origin=origin,
              selected_lifecycle="pending", selected_planner_identity=plan.get("planner_identity"),
              safety_status="safe", safety_blockers=[], prestart_status="not_required",
              physical_execution_enabled=False, execution_authority=False)
    return dict(plan=plan, r7=r7, checked_at=datetime(2026, 10, 17, 14, 5, tzinfo=timezone.utc),
                snapshot_identity="r7-cycle-1", controller_conflict=False,
                final_revalidation_safe=True, handoff_ready=True)


def test_manual_is_non_actuating_and_requires_atomic_revision():
    args = case()
    original = deepcopy(args)
    result = validate(**args)
    assert result["validation_status"] == "not_validated"
    assert "atomic_plan_revision_evidence" in result["missing_evidence"]
    assert result["execution_authorized"] is False and result["execution_performed"] is False
    assert args == original


def test_automatic_is_observed_without_promoting():
    result = validate(**case("automatic_72h_planner"))
    assert result["selected_plan_identity"] == "auto-123"
    assert result["execution_performed"] is False


def test_manual_direct_has_no_start_window_requirement():
    args = case(mode="direct")
    args["plan"].pop("start_time")
    assert "valid_start_window" not in validate(**args)["missing_evidence"]


def test_wrong_selection_is_blocked():
    args = case()
    args["r7"]["selected_slot"] = 1
    assert "r7_selection_mismatch" in validate(**args)["blockers"]


def test_missing_handoff_is_unknown():
    args = case()
    args["handoff_ready"] = None
    assert "handoff_evidence" in validate(**args)["missing_evidence"]


def test_nan_is_not_accepted():
    args = case()
    args["plan"]["power_w"] = float("nan")
    assert "plan_parameters" in validate(**args)["missing_evidence"]


def test_no_runtime_integration_imports():
    source = (Path(__file__).resolve().parents[1] / "custom_components/doems/ems_execution_readiness.py").read_text()
    assert "from homeassistant" not in source
    assert "async_call(" not in source
