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

def test_target_reached_blocks_charge():
    battery=dict(BATTERY,soc_percent=40)
    result=evaluate_execution(now=NOW,scheduler=SCHEDULER,plan=PLAN,battery=battery,source_fresh=True)
    assert "charge_target_reached" in result["blockers"]

def test_controller_conflict_blocks():
    result=decide(physical_execution_enabled=True,execution_authority=True,
                  controller_ready=True,controller_conflict=True)
    assert "controller_conflict" in result["blockers"]

def test_restart_requires_reconciliation():
    result=decide(previous={"status":"geblokkeerd","safe_return_required":True})
    assert result["safe_return_required"] is True
    assert "restart_requires_reconciliation" in result["blockers"]

def test_active_runtime_expiry_requires_safe_stop():
    started=NOW-timedelta(hours=2)
    initial=decide(physical_execution_enabled=True,execution_authority=True,
                   controller_ready=True,controller_conflict=False,device_acknowledged=True)
    active=dict(initial,started_at=started.isoformat())
    result=decide(previous=active)
    assert result["status"]=="stoppen"
    assert result["safe_return_required"] is True
    assert "runtime_elapsed" in result["blockers"]

def test_stopped_acknowledgement_clears_stop():
    result=decide(previous={"status":"stoppen"},device_stopped=True)
    assert result["status"]=="gestopt"
    assert result["safe_return_required"] is False

def test_retry_limit_blocks():
    result=decide(retries=3)
    assert "retry_limit" in result["blockers"]

def test_no_plan_is_not_executed():
    scheduler=dict(SCHEDULER,selected_slot=None)
    result=evaluate_execution(now=NOW,scheduler=scheduler,plan=None,battery=BATTERY,source_fresh=True)
    assert result["execution_performed"] is False

def test_active_identity_change_requires_stop():
    initial=decide(physical_execution_enabled=True,execution_authority=True,
                   controller_ready=True,controller_conflict=False,device_acknowledged=True)
    changed=dict(SCHEDULER,selected_planner_identity="changed")
    result=evaluate_execution(now=NOW,scheduler=changed,plan=PLAN,battery=BATTERY,
                              source_fresh=True,previous=initial)
    assert result["status"]=="stoppen"
    assert result["safe_return_required"] is True

def test_lost_controller_evidence_during_execution_requires_stop():
    active=decide(physical_execution_enabled=True,execution_authority=True,
                  controller_ready=True,controller_conflict=False,device_acknowledged=True)
    result=decide(previous=active,physical_execution_enabled=True,
                  execution_authority=True,controller_ready=False,
                  controller_conflict=None,device_acknowledged=True)
    assert result["status"]=="stoppen"
    assert result["safe_return_required"] is True

def test_lost_device_ack_during_execution_requires_stop():
    active=decide(physical_execution_enabled=True,execution_authority=True,
                  controller_ready=True,controller_conflict=False,device_acknowledged=True)
    result=decide(previous=active,physical_execution_enabled=True,
                  execution_authority=True,controller_ready=True,
                  controller_conflict=False,device_acknowledged=False)
    assert result["status"]=="stoppen"
    assert result["safe_return_required"] is True
