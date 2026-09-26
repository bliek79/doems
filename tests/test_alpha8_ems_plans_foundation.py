from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def test_alpha8_definitive_ems_components_exist() -> None:
    for name in (
        "ems_runtime.py",
        "ems_plan_store.py",
        "ems_scheduler.py",
        "ems_planner_bridge.py",
        "ems_soc.py",
        "number.py",
    ):
        assert (INTEGRATION / name).is_file()


def test_alpha8_plan_store_uses_definitive_namespace_and_three_slots() -> None:
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    store = (INTEGRATION / "ems_plan_store.py").read_text(encoding="utf-8")
    assert "PLAN_SLOT_COUNT = 3" in const
    assert 'f"{DOMAIN}.{entry_id}.plans"' in store
    assert "shadow_plans" not in store
    assert "class DOEMSPlanStore" in store
    assert "for slot in range(1, PLAN_SLOT_COUNT + 1)" in store
    assert '"origin": "manual"' in store
    assert '"origin"] = "manual"' in store
    assert '"automatic_72h_planner"' in store


def test_alpha8_runtime_is_independent_and_non_actuating() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    init = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    config = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    assert "class DOEMSEMSRuntime" in runtime
    assert "DOEMSPlanStore" in runtime
    assert "DOEMSScheduler" in runtime
    assert "build_planner_action_bridge" in runtime
    assert "run_planner_worker" in runtime
    assert "ems_multirate" in runtime
    assert 'execution_mode": "validation"' in runtime
    assert '"automatic_execution_armed": self._automatic_execution_armed' in runtime
    assert '"service_calls_performed": False' in runtime
    assert '"physical_execution_authority": False' in runtime
    assert ".services.async_call(" not in runtime
    assert "legacy_authority" not in runtime
    assert "legacy_automatic_execution" not in runtime
    assert "anker_ems" not in runtime
    assert "legacy_authority" not in init
    assert "legacy_automatic_execution" not in config


def test_alpha8_scheduler_priority_and_safety_contract() -> None:
    scheduler = (INTEGRATION / "ems_scheduler.py").read_text(encoding="utf-8")
    assert '0 if item.execution_mode == "gepland" else 1' in scheduler
    assert "item.ready_since" in scheduler
    assert "item.slot" in scheduler
    assert '"scheduler_physical_control": False' in scheduler
    assert "technical_min_soc_percent" in scheduler
    assert "max_soc_percent" in scheduler
    assert ".services.async_call(" not in scheduler


def test_alpha8_bridge_preserves_manual_priority_and_proven_semantics() -> None:
    bridge = (INTEGRATION / "ems_planner_bridge.py").read_text(encoding="utf-8")
    store = (INTEGRATION / "ems_plan_store.py").read_text(encoding="utf-8")
    frozen = (INTEGRATION / "ems_alpha76/const.py").read_text(encoding="utf-8")
    assert "MIN_ACTIONABLE_SAFETY_CHARGE_KWH = 0.10" in frozen
    assert "_EXECUTION_HANDOFF_ALLOWANCE_MIN = 2.0" in bridge
    assert '"plan_store_write_permitted"' in bridge
    assert '"scheduler_handoff_permitted"' in bridge
    assert "_manual_slot_available" in bridge
    assert "automatic_72h_planner" in bridge
    assert "manual" in store


def test_alpha8_public_entities_use_definitive_names() -> None:
    sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    select = (INTEGRATION / "select.py").read_text(encoding="utf-8")
    number = (INTEGRATION / "number.py").read_text(encoding="utf-8")
    dt = (INTEGRATION / "datetime.py").read_text(encoding="utf-8")
    combined = "\n".join((sensor, select, number, dt))
    for token in (
        "doems_ems",
        "doems_scheduler",
        "doems_plan_{slot}_status",
        "doems_plan_{slot}_{field}",
        "doems_plan_{slot}_start_time",
        "doems_plan_{slot}_{definition.object_suffix}",
    ):
        assert token in combined
    for field in ("action", "execution_mode", "power_w", "target_soc", "max_runtime_h", "max_start_delay_min"):
        assert field in combined
    assert "shadow_plan_" not in combined
    assert "legacy_" not in combined


def test_alpha8_complete_forecast_gate_and_rolling_price_window() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    live = (INTEGRATION / "ems_live_input.py").read_text(encoding="utf-8")
    prices = (INTEGRATION / "prices.py").read_text(encoding="utf-8")
    assert 'input_result.get("native_valid_slot_count") != 288' in runtime
    assert 'len(input_result.get("rows") or []) != 72' in runtime
    assert "price_window(window_start=window_start, slot_count=288)" in live
    assert "def price_window(" in prices


def test_alpha8_runtime_sequence_is_deterministic() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    start = runtime.index("async def _async_run_bridge_planstore_scheduler")
    end = runtime.index("    def snapshot", start)
    runtime = runtime[start:end]
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


def test_alpha8_no_step5c_or_legacy_runtime_files() -> None:
    assert not (INTEGRATION / "ems_step5c.py").exists()
    assert not (INTEGRATION / "ems_shadow_runtime.py").exists()


def test_alpha8_carries_quarter_roll_identity_continuity_into_definitive_bridge() -> None:
    bridge = (INTEGRATION / "ems_planner_bridge.py").read_text(encoding="utf-8")
    for token in (
        "continuity",
        "planner_identity",
        "planner_signature",
        "15 * 60",
    ):
        assert token in bridge
