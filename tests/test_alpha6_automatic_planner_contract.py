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


def _axis(home=0.0, solar=0.0, imp=0.30, exp=0.10):
    start=datetime(2026,10,7,0,0,tzinfo=timezone.utc)
    energy=[]; pv=[]; prices={}
    for i in range(288):
        a=start+timedelta(minutes=15*i); b=a+timedelta(minutes=15)
        energy.append({"start":a.isoformat(),"end":b.isoformat(),"home_kwh":home})
        pv.append({"start":a.isoformat(),"solar_kwh":solar})
        prices[a.isoformat()]={"time":a.isoformat(),"import_all_in":imp,"export_all_in":exp,"kind":"known_15m"}
    return energy,pv,prices


def _plan(start, action="ontladen", target=60, power=1000, runtime=1):
    return {"slot":1,"action":action,"execution_mode":"gepland","start_time":start.isoformat(),
            "power_w":power,"target_soc":target,"max_runtime_h":runtime,"max_start_delay_min":15,
            "lifecycle_status":"pending","origin":"manual"}


def test_alpha6_defaults_and_shadow_boundary():
    m=_load("automatic_planner_model")
    e,s,p=_axis()
    r=m.build_automatic_plan(energy_slots=e,solar_slots=s,plans=[],start_soc_percent=50,capacity_kwh=7.1,price_by_start=p)
    assert r["valid"] is True
    assert r["native_slot_count"] == 288
    assert r["planner_floor_soc_percent"] == 10.0
    assert r["technical_min_soc_percent"] == 5.0
    assert r["software_reserve_percent"] == 5.0
    assert r["capacity_kwh"] == 7.1
    assert r["capacity_source"] == "battery_input_contract_live_sensor"
    assert r["max_charge_power_w"] == 3500.0
    assert r["max_discharge_power_w"] == 3500.0
    assert r["automatic_planner_active"] is True
    assert r["automatic_plan_store_writes"] is False
    assert r["scheduler_active"] is False
    assert r["safety_prestart_active"] is False
    assert r["physical_execution_authority"] is False


def test_alpha6_capacity_is_runtime_input_not_fixed_7_1():
    m=_load("automatic_planner_model")
    e,s,p=_axis()
    a=m.build_automatic_plan(energy_slots=e,solar_slots=s,plans=[],start_soc_percent=50,capacity_kwh=7.1,price_by_start=p)
    b=m.build_automatic_plan(energy_slots=e,solar_slots=s,plans=[],start_soc_percent=50,capacity_kwh=14.2,price_by_start=p)
    assert a["capacity_kwh"] == 7.1
    assert b["capacity_kwh"] == 14.2
    assert b["planner_floor_kwh"] == 2*a["planner_floor_kwh"]


def test_alpha6_safety_charge_protects_ten_percent_floor():
    m=_load("automatic_planner_model")
    e,s,p=_axis()
    for i in range(8):
        e[i]["home_kwh"]=0.08
        p[e[i]["start"]]["import_all_in"]=0.10 if i==2 else 0.30
    r=m.build_automatic_plan(energy_slots=e,solar_slots=s,plans=[],start_soc_percent=15,capacity_kwh=7.1,price_by_start=p)
    assert r["safety_charge_needed"] is True
    assert "veiligheidsladen" in r["candidate_types"]
    assert r["projected_min_soc_percent"] >= 9.999
    assert r["safety_schedule_sufficient"] is True


def test_alpha6_peak_sale_requires_favorable_recharge_and_keeps_floor():
    m=_load("automatic_planner_model")
    e,s,p=_axis(home=0.01,imp=0.30,exp=0.10)
    p[e[4]["start"]]["export_all_in"]=0.60
    p[e[8]["start"]]["import_all_in"]=0.10
    r=m.build_automatic_plan(energy_slots=e,solar_slots=s,plans=[],start_soc_percent=80,capacity_kwh=7.1,price_by_start=p)
    assert "piek_ontladen" in r["candidate_types"]
    assert r["peak_sale_kwh"] > 0
    assert r["projected_min_soc_percent"] >= 9.999

    e2,s2,p2=_axis(home=0.01,imp=0.60,exp=0.10)
    p2[e2[4]["start"]]["export_all_in"]=0.50
    r2=m.build_automatic_plan(energy_slots=e2,solar_slots=s2,plans=[],start_soc_percent=80,capacity_kwh=7.1,price_by_start=p2)
    assert "piek_ontladen" not in r2["candidate_types"]


def test_alpha6_manual_commitment_has_hard_priority():
    m=_load("automatic_planner_model")
    e,s,p=_axis(home=0.01,imp=0.30,exp=0.10)
    start=datetime(2026,10,7,1,0,tzinfo=timezone.utc)
    p[e[4]["start"]]["export_all_in"]=0.70
    p[e[8]["start"]]["import_all_in"]=0.10
    r=m.build_automatic_plan(energy_slots=e,solar_slots=s,plans=[_plan(start)],start_soc_percent=80,capacity_kwh=7.1,price_by_start=p)
    manual=[row for row in r["native_slots"] if row["manual_slots"]]
    assert manual
    assert all(row["automatic_action"] == "geen_actie" for row in manual)
    assert r["manual_commitment_slots"] == [1]


def test_alpha6_normal_arbitrage_is_separate_from_peak_sale():
    m=_load("automatic_planner_model")
    e,s,p=_axis(home=0.0,imp=0.30,exp=0.10)
    p[e[4]["start"]]["import_all_in"]=0.10
    p[e[8]["start"]]["export_all_in"]=0.45
    r=m.build_automatic_plan(energy_slots=e,solar_slots=s,plans=[],start_soc_percent=10,capacity_kwh=7.1,
                             price_by_start=p,peak_sale_threshold_eur_per_kwh=0.80)
    assert "handelsladen" in r["candidate_types"]
    assert "handel_ontladen" in r["candidate_types"]
    assert "piek_ontladen" not in r["candidate_types"]
    assert r["trade_charge_kwh"] > 0
    assert r["trade_discharge_kwh"] > 0


def test_alpha6_missing_price_slot_blocks_fail_closed():
    m=_load("automatic_planner_model")
    e,s,p=_axis(); p.pop(e[20]["start"])
    r=m.build_automatic_plan(energy_slots=e,solar_slots=s,plans=[],start_soc_percent=50,capacity_kwh=7.1,price_by_start=p)
    assert r["valid"] is False
    assert "price_slot_20_missing" in r["blockers"]


def test_alpha6_public_surface_and_source_are_read_only():
    const=(INTEGRATION/"const.py").read_text(encoding="utf-8")
    sensor=(INTEGRATION/"sensor.py").read_text(encoding="utf-8")
    runtime=(INTEGRATION/"automatic_planner.py").read_text(encoding="utf-8")
    model=(INTEGRATION/"automatic_planner_model.py").read_text(encoding="utf-8")
    init=(INTEGRATION/"__init__.py").read_text(encoding="utf-8")
    assert 'VERSION = "0.2.0-alpha.6.3"' in const
    assert 'DEFAULT_SOFTWARE_RESERVE_PERCENT = 5.0' in const
    assert 'DEFAULT_MAX_CHARGE_POWER_W = 3500.0' in const
    assert 'DEFAULT_MAX_DISCHARGE_POWER_W = 3500.0' in const
    assert 'DEFAULT_PEAK_SALE_THRESHOLD_EUR_PER_KWH = 0.50' in const
    assert "doems_automatic_planner" in sensor
    assert "doems_automatic_soc_projection_timeline" in sensor
    assert "doems_ems_plan72_hours" in sensor
    assert "DOEMSAutomaticPlanner" in init
    active=runtime+model
    assert "async_call(" not in active
    assert "third_party_control" not in active
    assert "DOEMSScheduler" not in active
    assert "async_write" not in active
