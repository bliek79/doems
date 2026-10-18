from datetime import datetime, timezone, timedelta
from custom_components.doems.execution_model import evaluate_execution

NOW = datetime(2026, 10, 18, 8, 5, tzinfo=timezone.utc)
PLAN = {"action":"laden","origin":"automatic_72h_planner","lifecycle_status":"pending",
        "planner_identity":"id-1","lifecycle_updated_at":"rev-1","execution_mode":"gepland",
        "start_time":"2026-10-18T08:00:00+00:00","max_start_delay_min":15,
        "power_w":2360,"target_soc":36,"max_runtime_h":1}
SCHEDULER = {"selected_slot":1,"selected_action":"laden","selected_origin":"automatic_72h_planner",
             "selected_planner_identity":"id-1","selected_lifecycle":"pending",
             "safety_status":"safe","safety_blockers":[],"prestart_status":"not_required",
             "prestart_blockers":[],"physical_execution_enabled":False,"execution_authority":False}
BATTERY = {"status":"ready","direction_consistent":True,"status_direction_consistent":True,
           "soc_percent":25}

def decide(**kwargs):
    return evaluate_execution(now=NOW,scheduler=SCHEDULER,plan=PLAN,battery=BATTERY,
                              source_fresh=True,**kwargs)

def test_safe_observation():
    result=decide()
    assert result["status"]=="voorbereid"
    assert result["execution_performed"] is False

def test_never_claims_physical_execution_without_acknowledgement():
    result=decide(physical_execution_enabled=True,execution_authority=True,
                  controller_ready=True,controller_conflict=False)
    assert result["status"]=="start_wacht_op_bevestiging"
    assert result["execution_performed"] is False

def test_expired_window_blocks():
    result=evaluate_execution(now=NOW+timedelta(hours=1),scheduler=SCHEDULER,
                              plan=PLAN,battery=BATTERY,source_fresh=True)
    assert "outside_start_window" in result["blockers"]

def test_changed_identity_blocks():
    changed=dict(SCHEDULER,selected_planner_identity="other")
    result=evaluate_execution(now=NOW,scheduler=changed,plan=PLAN,battery=BATTERY,source_fresh=True)
    assert "planner_identity_changed" in result["blockers"]

def test_stale_battery_blocks():
    result=evaluate_execution(now=NOW,scheduler=SCHEDULER,plan=PLAN,battery=BATTERY,source_fresh=False)
    assert "battery_input_unavailable" in result["blockers"]
