from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "doems" / "solar_reference_freeze.py"


def _module():
    spec = importlib.util.spec_from_file_location("freeze_contract", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _states(module):
    start = datetime(2026, 9, 16, 8, 15, tzinfo=timezone.utc)
    points=[]
    for index in range(module.REFERENCE_SLOT_COUNT):
        ts=int((start + timedelta(minutes=15*index)).timestamp()*1000)
        points.append([ts,0.01,0.02,0.03,0.04,0.08,0.12,100.0,200.0])
    end=start+timedelta(hours=72)
    base={entity:{"state":"0","attributes":{}} for entity in module.REFERENCE_ENTITY_IDS}
    base[module.ENTITY_STATUS]={"state":"ok","attributes":{"endpoint":"api.open-meteo.com/v1/forecast"}}
    base[module.ENTITY_MODEL]={"state":module.REFERENCE_MODEL,"attributes":{"provider":"Open-Meteo"}}
    base[module.ENTITY_TIMELINE]={"state":"288","attributes":{"source":"open_meteo","model":"best_match","resolution_minutes":15,"horizon_hours":72,"slot_count":288,"point_count":288,"source_buffer_point_count":292,"point_format":module.REFERENCE_POINT_FORMAT,"interval_semantics":"slot_start; Open-Meteo backward-average timestamp shifted by 15 minutes","forecast_start":start.isoformat(),"last_slot_start":(end-timedelta(minutes=15)).isoformat(),"forecast_end":end.isoformat(),"points":points}}
    base[module.ENTITY_NEXT_QUARTER]={"state":"0.03","attributes":{"start":start.isoformat(),"north_kwh":0.01,"south_kwh":0.02}}
    for entity in module.NUMERIC_STATE_ENTITIES:
        base.setdefault(entity,{"state":"0","attributes":{}})
        if entity != module.ENTITY_NEXT_QUARTER:
            base[entity]["state"]="0.0"
    return base


def test_valid_reference_is_capture_ready_and_snapshot_is_immutable_shape() -> None:
    module=_module(); states=_states(module)
    assert module.validate_reference(states)==[]
    captured_utc=datetime(2026,9,16,9,3,4,tzinfo=timezone.utc)
    captured_local=datetime(2026,9,16,11,3,4,tzinfo=timezone(timedelta(hours=2)))
    snapshot=module.build_snapshot(states,captured_at_utc=captured_utc,captured_at_local=captured_local)
    assert snapshot["snapshot_id"]=="A41-SOLAR-20260916T090304Z"
    assert snapshot["reference"]["release"]=="0.2.0-alpha.41"
    assert snapshot["reference"]["commit"]=="0dbf9dd68345d9a5dd96d82591aa1d8b93689415"
    assert len(snapshot["timeline"]["points"])==288
    assert len(snapshot["timeline"]["raw_points_sha256"])==64
    assert snapshot["sheets_anchor"]["mode"]=="read_only"
    assert snapshot["sheets_anchor"]["status"]=="pending_verification"


def test_reference_blocks_incomplete_timeline() -> None:
    module=_module(); states=_states(module)
    states[module.ENTITY_TIMELINE]["attributes"]["points"]=states[module.ENTITY_TIMELINE]["attributes"]["points"][:-1]
    assert "timeline_raw_points_not_288" in module.validate_reference(states)


def test_reference_blocks_non_ok_source_and_missing_actual() -> None:
    module=_module(); states=_states(module)
    states[module.ENTITY_STATUS]["state"]="stale"
    states[module.ENTITY_ACTUAL_TOTAL]["state"]="unavailable"
    blockers=module.validate_reference(states)
    assert "source_status_not_ok:stale" in blockers
    assert f"unavailable_entity:{module.ENTITY_ACTUAL_TOTAL}" in blockers
    assert f"numeric_state_invalid:{module.ENTITY_ACTUAL_TOTAL}" in blockers
