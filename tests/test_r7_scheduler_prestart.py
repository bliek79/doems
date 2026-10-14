"""R7 scheduler, start-window and non-actuating safety decisions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "doems"
# Load pure model through its real package for shared R6 contract imports,
# without executing the Home Assistant integration entrypoint.
for package, location in (
    ("custom_components", ROOT / "custom_components"),
    ("custom_components.doems", COMPONENT),
):
    module = sys.modules.get(package)
    if module is None:
        module = types.ModuleType(package)
        sys.modules[package] = module
    module.__path__ = [str(location)]
spec = importlib.util.spec_from_file_location(
    "custom_components.doems.r7_model_tested", COMPONENT / "r7_model.py"
)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
NOW = datetime(2026, 10, 13, 13, 15, tzinfo=timezone.utc)


def plan(slot=1, **changes):
    result = {
        "origin": model.AUTO_ORIGIN, "action": "laden", "execution_mode": "gepland",
        "start_time": NOW.isoformat(), "max_start_delay_min": 10,
        "max_runtime_h": 1, "power_w": 700, "target_soc": 70,
        "planned_end_time": (NOW + timedelta(hours=1)).isoformat(),
        "lifecycle_status": "concept", "lifecycle_updated_at": "rev1",
        "planner_identity": f"identity-{slot}", "planner_signature": f"signature-{slot}",
    }
    return {**result, **changes}


def bundle():
    return {
        "status": "ready", "valid": True, "planner_published_generation": 5,
        "automatic": {"valid": True, "native_slot_count": 288},
        "combined": {
            "status": "ready", "valid": True, "native_slot_count": 288,
            "max_charge_power_w": 3500, "max_discharge_power_w": 3500,
            "planner_floor_soc_percent": 14,
        },
    }


def battery():
    return {
        "status": "ready", "soc_percent": 30, "capacity_kwh": 7.1,
        "charge_power_w": 0, "discharge_power_w": 0,
        "direction_consistent": True, "status_direction_consistent": True,
    }


def evaluate(plans=None, now=NOW, b=None, bat=None, bridge=True, fresh=True):
    return model.evaluate_r7(
        now=now, plans=plans if plans is not None else {1: plan()},
        bundle=b if b is not None else bundle(),
        battery=bat if bat is not None else battery(),
        bridge_ready=bridge, planner_generation=5, source_fresh=fresh,
    )


def test_automatic_due_exact_start_and_deadline_both_pass():
    assert evaluate()["can_promote"]
    assert evaluate(now=NOW + timedelta(minutes=10))["can_promote"]


def test_before_start_is_not_due():
    result = evaluate(now=NOW - timedelta(seconds=1))
    assert result["selected_slot"] is None
    assert not result["can_promote"]
    assert result["slots"][1] == "wachtend"


def test_after_end_is_r6_expiry_not_r7_promotion():
    result = evaluate(now=NOW + timedelta(minutes=10, seconds=1))
    assert result["selected_slot"] is None
    assert not result["can_promote"]
    assert result["slots"][1] == "verlopen_in_afwachting_r6"


def test_earliest_start_then_slot_number_deterministic():
    entries = {1: plan(1, start_time=(NOW - timedelta(minutes=1)).isoformat()),
               2: plan(2, start_time=(NOW - timedelta(minutes=5)).isoformat()),
               3: plan(3, start_time=(NOW - timedelta(minutes=5)).isoformat())}
    assert evaluate(plans=entries)["selected_slot"] == 2


def test_manual_concept_never_automatically_pending():
    result = evaluate(plans={1: plan(origin="manual")})
    assert result["selected_slot"] is None
    assert not result["can_promote"]
    assert result["slots"][1] == "handmatig_concept"


def test_manual_pending_observed_only_without_execution():
    result = evaluate(plans={1: plan(origin="manual", lifecycle_status="pending")})
    assert result["status"] == "manual_pending_observe"
    assert not result["can_promote"]
    assert result["execution_authority"] is False


def test_automatic_pending_not_repromoted():
    result = evaluate(plans={1: plan(lifecycle_status="pending")})
    assert result["status"] == "automatic_pending_observe"
    assert not result["can_promote"]


def test_incomplete_r5_generation_fails_closed():
    stale = bundle()
    stale["planner_published_generation"] = 4
    result = evaluate(b=stale)
    assert "r5_bundle_not_current" in result["prestart_blockers"]
    assert not result["can_promote"]


def test_less_than_288_quarters_fails_closed():
    bad = bundle()
    bad["combined"]["native_slot_count"] = 287
    assert not evaluate(b=bad)["can_promote"]


def test_r6_not_current_fails_closed():
    assert "r6_bridge_not_ready" in evaluate(bridge=False)["prestart_blockers"]


def test_missing_identity_or_signature_blocks():
    bad = plan(planner_identity=None)
    assert "automatic_identity_missing" in evaluate(plans={1: bad})["prestart_blockers"]
    bad = plan(planner_signature=None)
    assert not evaluate(plans={1: bad})["can_promote"]


def test_safety_blocks_missing_and_stale_source():
    assert "battery_sources_stale" in evaluate(fresh=False)["safety_blockers"]
    bad = battery()
    bad["status"] = "blocked"
    assert "battery_input_not_ready" in evaluate(bat=bad)["safety_blockers"]


def test_charge_target_and_power_bounds():
    result = evaluate(plans={1: plan(target_soc=25, power_w=3550)})
    assert "charge_target_already_reached" in result["safety_blockers"]
    assert "power_invalid" in result["safety_blockers"]


def test_conflicting_observation_blocks():
    bad = battery()
    bad["direction_consistent"] = False
    assert "battery_power_conflict" in evaluate(bat=bad)["safety_blockers"]


def test_discharge_hard_floor_from_r5():
    bad = evaluate(plans={1: plan(action="ontladen", target_soc=10)})
    assert "execution_reserve_reached" in bad["safety_blockers"]
    good = evaluate(plans={1: plan(action="ontladen", target_soc=20)})
    assert good["can_promote"]
    missing = bundle()
    del missing["combined"]["planner_floor_soc_percent"]
    assert "execution_reserve_unavailable" in evaluate(
        plans={1: plan(action="ontladen", target_soc=20)}, b=missing
    )["safety_blockers"]


def test_starttime_timezone_required():
    assert evaluate(plans={1: plan(start_time="not-a-date")})["slots"][1] == "ongeldig"
    assert evaluate(plans={1: plan(start_time="2026-10-13T13:15:00")})["slots"][1] == "ongeldig"


def test_no_r7_physical_actuator_calls():
    for name in ("r7_model.py", "r7_runtime.py"):
        code = (COMPONENT / name).read_text(encoding="utf-8")
        assert "doems.start_plan_now" not in code
        assert "async_call(" not in code
        assert "modbus" not in code.lower()
        assert "execution_authority" in code or name == "r7_runtime.py"
    for items in ({1: plan()}, {1: plan(origin="manual", lifecycle_status="pending")}):
        result = evaluate(plans=items)
        assert not result["physical_execution_enabled"]
        assert not result["execution_authority"]
