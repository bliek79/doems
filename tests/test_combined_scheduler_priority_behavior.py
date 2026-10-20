"""Combined manual/automatic selection using the production scheduler."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "custom_components" / "doems" / "ems_scheduler.py").read_text()
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _scheduler():
    tree = ast.parse(SOURCE)
    selected = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in {"SchedulerCandidate", "DOEMSScheduler"}]
    # Preserve dataclass decorator and annotation semantics in the source module.
    ns = {"__name__": "test_combined_scheduler_priority_behavior", "dataclass": __import__("dataclasses").dataclass,
          "datetime": datetime, "timedelta": timedelta, "Any": __import__("typing").Any,
          "PLAN_SLOT_COUNT": 3, "DOEMSPlanStore": object,
          "dt_util": type("DT", (), {"now": staticmethod(lambda: NOW),
                                     "parse_datetime": staticmethod(datetime.fromisoformat),
                                     "DEFAULT_TIME_ZONE": timezone.utc})}
    import sys
    import types
    module = types.ModuleType(ns["__name__"])
    sys.modules[module.__name__] = module
    module.__dict__.update(ns)
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), "<scheduler>", "exec"), module.__dict__)
    return module.DOEMSScheduler


def _plan(origin, start, *, action="laden", mode="gepland"):
    return {"action": action, "origin": origin, "execution_mode": mode,
            "power_w": 500, "target_soc": 80, "max_runtime_h": 1,
            "max_start_delay_min": 120, "start_time": start.isoformat(),
            "lifecycle_status": "pending"}


def _evaluate(plans):
    store = type("Store", (), {"get_plan": lambda self, slot: plans.get(slot, {"action": "geen"})})()
    return _scheduler()(store).evaluate(now=NOW)


def test_due_manual_wins_even_when_automatic_was_due_earlier():
    plans = {1: _plan("automatic_72h_planner", NOW - timedelta(minutes=40)),
             2: _plan("manual", NOW - timedelta(minutes=5))}
    state = _evaluate(plans)
    assert state["scheduler_selected_slot"] == 2
    assert state["scheduler_slots"][1]["status"] == "geblokkeerd"


def test_automatic_selected_when_manual_not_due():
    plans = {1: _plan("automatic_72h_planner", NOW - timedelta(minutes=5)),
             2: _plan("manual", NOW + timedelta(minutes=20))}
    state = _evaluate(plans)
    assert state["scheduler_selected_slot"] == 1


def test_manual_direct_wins_over_due_automatic():
    plans = {1: _plan("automatic_72h_planner", NOW - timedelta(minutes=5)),
             2: _plan("manual", NOW, mode="direct")}
    state = _evaluate(plans)
    assert state["scheduler_selected_slot"] == 2


def test_automatic_order_remains_oldest_due_first():
    plans = {1: _plan("automatic_72h_planner", NOW - timedelta(minutes=5)),
             2: _plan("automatic_72h_planner", NOW - timedelta(minutes=20))}
    state = _evaluate(plans)
    assert state["scheduler_selected_slot"] == 2
