from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"


def _read(name: str) -> str:
    return (INTEGRATION / name).read_text(encoding="utf-8")


def test_alpha33_runtime_adapter_is_explicitly_canonical_and_behavior_preserving() -> None:
    runtime = _read("ems_runtime.py")
    assert "self._state_publish_lock = asyncio.Lock()" in runtime
    assert "runtime_snapshot_adapter" in runtime
    assert "alpha33_alpha76_serialized_coordinator_v1" in runtime
    assert "Behavior-preserving platform adapter" in runtime


def test_planner_publication_and_fast_execution_refresh_share_one_serialization_boundary() -> None:
    runtime = _read("ems_runtime.py")

    planner_anchor = runtime.index("async with self._state_publish_lock:")
    planner_publish = runtime.index("self.planner_result = planner_result", planner_anchor)
    planner_chain = runtime.index("await self._async_run_bridge_planstore_scheduler()", planner_publish)
    assert planner_anchor < planner_publish < planner_chain

    fast_start = runtime.index(
        "    async def _async_fast_execution_refresh(self, trigger: str) -> None:"
    )
    fast_locked = runtime.index(
        "await self._async_fast_execution_refresh_locked(trigger)", fast_start
    )
    next_method = runtime.index(
        "    async def _async_fast_execution_refresh_locked", fast_locked
    )
    fast_block = runtime[fast_start:next_method]
    assert "async with self._state_publish_lock:" in fast_block


def test_runtime_adapter_does_not_change_frozen_alpha76_decision_or_execution_modules() -> None:
    parity = (ROOT / "tests" / "test_alpha32_full_anker_alpha76_parity.py").read_text(
        encoding="utf-8"
    )
    # Alpha33 is a host-runtime adapter only. The existing source-blob guard remains
    # the authority for Scheduler/Safety/Execution/Planner parity.
    for module in (
        "ems_execution.py",
        "ems_scheduler.py",
        "ems_prestart_validator.py",
        "ems_safety_guard.py",
        "ems_action_controller.py",
        "energy_need.py",
        "planner_preview.py",
        "planner_72h.py",
    ):
        assert module in parity


def test_manual_scheduled_execution_remains_independent_of_automatic_arm() -> None:
    runtime = _read("ems_runtime.py")
    start = runtime.index("    def _schedule_manual_physical_start")
    end = runtime.index("    @property\n    def control_entity_ids", start)
    block = runtime[start:end]
    manual = block[block.index('        if origin != "manual":'):]
    assert "_automatic_execution_armed" not in manual
    assert "await self.execution.async_execute_selected_plan()" in manual
    assert "retry_wait:" in manual
