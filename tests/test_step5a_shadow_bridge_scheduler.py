from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"
ALPHA = INTEGRATION / "ems_alpha76"


def test_shadow_bridge_planstore_scheduler_modules_are_present() -> None:
    for name in ("planner_action_bridge.py", "plan_store.py", "scheduler.py"):
        assert (ALPHA / name).is_file()


def test_shadow_plan_store_is_isolated_and_three_slot_contract_is_frozen() -> None:
    const = (ALPHA / "const.py").read_text(encoding="utf-8")
    store = (ALPHA / "plan_store.py").read_text(encoding="utf-8")
    assert 'DOMAIN = "doems"' in const
    assert "PLAN_SLOT_COUNT = 3" in const
    assert 'f"{DOMAIN}.{entry_id}.shadow_plans"' in store
    assert "for slot in range(1, PLAN_SLOT_COUNT + 1)" in store
    assert '"origin": "manual"' in store
    assert '"origin"] = "manual"' in store
    assert 'plan.get("origin") or "") != "automatic_72h_planner"' in store


def test_bridge_keeps_frozen_action_thresholds_and_handoff_semantics() -> None:
    bridge = (ALPHA / "planner_action_bridge.py").read_text(encoding="utf-8")
    const = (ALPHA / "const.py").read_text(encoding="utf-8")
    assert "MIN_ACTIONABLE_SAFETY_CHARGE_KWH = 0.10" in const
    assert "_EXECUTION_HANDOFF_ALLOWANCE_MIN = 2.0" in bridge
    assert "math.ceil(power_w / 10.0) * 10" in bridge
    assert '"veiligheidsladen"' in bridge
    assert '"veiligheidsladen+handelsladen"' in bridge
    assert '"handelsladen"' in bridge
    assert '"handel_ontladen"' in bridge
    assert '"origin": "automatic_72h_planner"' in bridge
    assert '"plan_store_write_permitted"' in bridge
    assert '"scheduler_handoff_permitted"' in bridge


def test_scheduler_keeps_frozen_priority_and_never_controls_physical_device() -> None:
    scheduler = (ALPHA / "scheduler.py").read_text(encoding="utf-8")
    assert '0 if item.execution_mode == "gepland" else 1' in scheduler
    assert "item.ready_since" in scheduler
    assert "item.slot" in scheduler
    assert '"scheduler_physical_control": False' in scheduler
    assert ".services.async_call(" not in scheduler


def test_runtime_mirrors_frozen_bridge_store_scheduler_sequence() -> None:
    runtime = (INTEGRATION / "ems_shadow_runtime.py").read_text(encoding="utf-8")
    order = [
        "pre_cleanup_scheduler = self.scheduler.evaluate(",
        "async_release_expired_automatic_plans(expired_slots)",
        "scheduler_snapshot = self.scheduler.evaluate(",
        "bridge = build_planner_action_bridge(data, now=self.last_refresh)",
        "async_sync_automatic_plans(",
        "async_handoff_automatic_plans(",
        "self.scheduler_result = self.scheduler.evaluate(",
        "refreshed_bridge = build_planner_action_bridge(",
    ]
    positions = [runtime.index(marker) for marker in order]
    assert positions == sorted(positions)


def test_shadow_chain_extends_through_non_actuating_downstream_gates() -> None:
    runtime = (INTEGRATION / "ems_shadow_runtime.py").read_text(encoding="utf-8")
    assert '"prestart_validator_invoked": bool(self.downstream_result)' in runtime
    assert '"safety_guard_invoked": bool(self.downstream_result)' in runtime
    assert '"action_controller_invoked": bool(self.downstream_result)' in runtime
    assert '"execution_controller_invoked": bool(self.downstream_result)' in runtime
    assert '"automatic_execution_armed": False' in runtime
    assert '"mode_switch_service_calls_available": False' in runtime
    assert '"service_calls_performed": False' in runtime
    assert '"physical_execution_authority": False' in runtime
    assert ".services.async_call(" not in runtime


def test_shadow_sensor_exposes_compact_three_slot_diagnostics() -> None:
    runtime = (INTEGRATION / "ems_shadow_runtime.py").read_text(encoding="utf-8")
    for field in (
        "bridge_status",
        "bridge_candidate_count",
        "shadow_plan_store_write_gate_open",
        "shadow_scheduler_status",
        "shadow_scheduler_selected_slot",
        "shadow_slot_1",
        "shadow_slot_2",
        "shadow_slot_3",
    ):
        assert f'"{field}"' in runtime
