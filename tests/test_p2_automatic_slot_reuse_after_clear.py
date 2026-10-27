"""Regression: a cleared R6 proposal must not permanently reserve a shared slot."""
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.doems.manual_plan_model import new_manual_plan
from custom_components.doems.manual_plan_store import (
    DOEMSManualPlanStore, AUTO_ORIGIN,
)


@pytest.mark.asyncio
async def test_auto_proposal_cleared_is_reusable_without_overwriting_manual():
    store = object.__new__(DOEMSManualPlanStore)
    cleared = new_manual_plan()
    cleared["lifecycle_reason"] = "automatic_proposal_cleared"
    manual = new_manual_plan()
    manual.update({"action": "laden", "lifecycle_status": "concept",
                   "origin": "manual"})
    store._plans = {1: cleared, 2: manual, 3: new_manual_plan()}
    saves = []
    async def save():
        saves.append(True)
    store._async_save = save
    store._notify_automatic = lambda: None
    now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    start, end = now + timedelta(hours=1), now + timedelta(hours=2)
    proposal = {
        "origin": AUTO_ORIGIN, "action": "laden",
        "planner_identity": "new-r6-candidate",
        "planner_signature": "signature-1",
        "start_time": start.isoformat(), "planned_end_time": end.isoformat(),
        "power_w": 1000, "target_soc": 80, "max_runtime_h": 1,
    }
    result = await DOEMSManualPlanStore.async_sync_automatic_plans(
        store, [proposal], now=now
    )
    assert result["written_slots"] == [1]
    assert store._plans[1]["origin"] == AUTO_ORIGIN
    assert store._plans[1]["planner_identity"] == "new-r6-candidate"
    assert store._plans[2] == manual
    assert saves
