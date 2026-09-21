from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"
ALPHA = INTEGRATION / "ems_alpha76"


def _load_alpha(name: str):
    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package
    if "custom_components.doems" not in sys.modules:
        package = types.ModuleType("custom_components.doems")
        package.__path__ = [str(INTEGRATION)]
        sys.modules["custom_components.doems"] = package
    if "custom_components.doems.ems_alpha76" not in sys.modules:
        package = types.ModuleType("custom_components.doems.ems_alpha76")
        package.__path__ = [str(ALPHA)]
        sys.modules["custom_components.doems.ems_alpha76"] = package
    return importlib.import_module(f"custom_components.doems.ems_alpha76.{name}")


def _ready_data() -> dict:
    return {
        "scheduler_selected_slot": 1,
        "scheduler_ready": True,
        "scheduler_slots": {
            1: {
                "origin": "automatic_72h_planner",
                "purpose": "veiligheidsladen",
                "action": "laden",
                "planner_identity": "plan-1",
                "power_w": 1200,
                "target_soc": 60,
                "max_runtime_h": 1.0,
                "start_time": "2026-09-21T11:00:00+00:00",
                "price_sources": ["known"],
                "all_prices_known": True,
            }
        },
        "auto_prestart_safe": True,
        "auto_safety_handoff_safe": True,
        "auto_execution_handoff_ready": True,
        "auto_final_revalidation_safe": True,
        "auto_mode_switch_preview_ready": True,
        "auto_plan_72h_execution_buffer_safe": False,
        "forecast_ready": True,
        "control_path_configured": True,
        "physical_test_active": False,
        "execution_active": False,
        "execution_origin": None,
    }


def _ready_readiness() -> dict:
    return {
        "ready": True,
        "reason": "control_path_ready",
        "stable_seconds": 120.0,
        "required_stable_seconds": 60.0,
        "pre_mode_ready": True,
        "pre_mode_reason": "pre_mode_ready",
        "pre_mode_stable_seconds": 120.0,
        "post_mode_ready": False,
        "post_mode_reason": "awaiting_third_party_control",
        "post_mode_stable_seconds": 0.0,
        "post_mode_required": False,
        "entities": {},
    }


def test_final_shadow_is_idle_without_scheduler_selection() -> None:
    m = _load_alpha("automatic_execution_shadow")
    data = _ready_data()
    data["scheduler_selected_slot"] = None
    data["scheduler_ready"] = False

    result = m.build_automatic_execution_shadow(
        data, readiness=_ready_readiness(), armed=False
    )

    assert result["auto_shadow_status"] == "idle"
    assert result["auto_shadow_technical_ready"] is False
    assert "no_automatic_action_selected" in result["auto_shadow_blockers"]
    assert result["auto_shadow_execution_permitted"] is False
    assert result["auto_shadow_physical_control"] is False


def test_final_shadow_blocks_when_control_path_is_not_stable() -> None:
    m = _load_alpha("automatic_execution_shadow")
    readiness = _ready_readiness()
    readiness.update(
        {
            "ready": False,
            "reason": "operating_mode_not_stable",
            "stable_seconds": 20.0,
            "pre_mode_ready": False,
            "pre_mode_reason": "operating_mode_not_stable",
            "pre_mode_stable_seconds": 20.0,
        }
    )

    result = m.build_automatic_execution_shadow(
        _ready_data(), readiness=readiness, armed=False
    )

    assert result["auto_shadow_status"] == "blocked"
    assert result["auto_shadow_technical_ready"] is False
    assert "control_path_not_stable" in result["auto_shadow_blockers"]
    assert result["auto_shadow_control_path_required_stable_seconds"] == 60.0
    assert result["auto_shadow_execution_permitted"] is False


def test_final_shadow_reaches_ready_disarmed_but_never_execution_permission() -> None:
    m = _load_alpha("automatic_execution_shadow")
    result = m.build_automatic_execution_shadow(
        _ready_data(), readiness=_ready_readiness(), armed=True
    )

    assert result["auto_shadow_status"] == "ready_disarmed"
    assert result["auto_shadow_technical_ready"] is True
    assert result["auto_shadow_blockers"] == []
    assert result["auto_shadow_armed"] is False
    assert result["auto_shadow_execution_permitted"] is False
    assert result["auto_shadow_physical_control"] is False


def test_trade_requires_known_prices() -> None:
    m = _load_alpha("automatic_execution_shadow")
    data = _ready_data()
    data["scheduler_slots"][1]["purpose"] = "handelsladen"
    data["scheduler_slots"][1]["all_prices_known"] = False

    result = m.build_automatic_execution_shadow(
        data, readiness=_ready_readiness(), armed=False
    )

    assert result["auto_shadow_status"] == "blocked"
    assert "trade_requires_known_prices" in result["auto_shadow_blockers"]


def test_runtime_mirrors_alpha76_60_second_two_stage_stability() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert "required_stable_seconds = 60.0" in runtime
    assert 'mode["stable_seconds"] < required_stable_seconds' in runtime
    assert 'mode["state"] == "third_party_control"' in runtime
    assert 'direction["stable_seconds"] < required_stable_seconds' not in runtime
    assert 'item["stable_seconds"] < required_stable_seconds' in runtime
    assert '"awaiting_third_party_control"' in runtime


def test_runtime_places_final_shadow_after_mode_switch_preview() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    mode=runtime.index("work.update(self.execution_gates.evaluate_mode_switch_transaction(work))")
    final=runtime.index("build_automatic_execution_shadow(")
    legacy=runtime.index("work.update(self.safety_guard.evaluate(work))")
    assert mode < final < legacy


def test_alpha722_keeps_physical_boundary_closed() -> None:
    runtime=(INTEGRATION/"ems_shadow_runtime.py").read_text(encoding="utf-8")
    shadow=(ALPHA/"automatic_execution_shadow.py").read_text(encoding="utf-8")
    assert ".services.async_call(" not in runtime
    assert ".services.async_call(" not in shadow
    assert "async def async_run_" not in shadow
    assert "armed = bool(armed) and False" in shadow
    assert "execution_permitted = False" in shadow
    assert '"physical_execution_authority": False' in runtime
