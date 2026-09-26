from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib
from pathlib import Path
from types import SimpleNamespace
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "doems"

START = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
SETTINGS = SimpleNamespace(
    battery_capacity_kwh=7.2,
    technical_min_soc_percent=5,
    max_soc_percent=100,
    max_charge_power_w=3200,
    max_discharge_power_w=3200,
    software_reserve_percent=7.0,
    charge_efficiency_percent=92.0,
    discharge_efficiency_percent=92.0,
    minimum_trade_margin_eur_per_kwh=0.10,
    startup_delay_seconds=30,
)


def _install_stubs() -> None:
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
        package.__path__ = [str(INTEGRATION / "ems_alpha76")]
        sys.modules["custom_components.doems.ems_alpha76"] = package

    ha = types.ModuleType("homeassistant")
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")
    dt.UTC = timezone.utc
    dt.DEFAULT_TIME_ZONE = timezone.utc
    dt.utcnow = lambda: datetime.now(timezone.utc)
    dt.now = lambda: datetime.now(timezone.utc)
    dt.parse_datetime = lambda value: datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    util.dt = dt
    ha.util = util
    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.util", util)
    sys.modules.setdefault("homeassistant.util.dt", dt)


def _input_result() -> dict:
    rows = []
    for index in range(72):
        start = START + timedelta(hours=index)
        price = 0.30
        if index == 6:
            price = 0.20
        if index == 18:
            price = 0.10
        rows.append(
            {
                "start": start.isoformat(),
                "home_kwh": 0.25,
                "solar_kwh": 0.0,
                "solar_valid": True,
                "import_price": price,
                "export_price": price,
                "price_source": "test",
                "import_price_source": "test",
                "export_price_source": "test",
            }
        )
    return {
        "status": "ready",
        "native_valid_slot_count": 288,
        "rows": rows,
        "time_contract": {"window_start": START.isoformat()},
    }


def test_alpha20_policy_source_is_byte_frozen() -> None:
    digest = hashlib.sha256(
        (INTEGRATION / "ems_policy_alpha20.py").read_bytes()
    ).hexdigest()
    assert digest == "cf5f46e7c7cca492f7fb95df062d96db9109f0dc256144885c82efd9ea573eb8"


def test_multirate_worker_returns_exact_alpha20_bundle() -> None:
    _install_stubs()
    policy = importlib.import_module("custom_components.doems.ems_policy_alpha20")
    multirate = importlib.import_module("custom_components.doems.ems_multirate")
    input_result = _input_result()

    expected = policy.run_ems_chain(
        input_result=input_result,
        settings=SETTINGS,
        soc_percent=25.0,
        now=START,
    )
    actual = multirate.run_planner_worker(
        input_result=input_result,
        settings=SETTINGS,
        soc_percent=25.0,
        reference=START,
    )
    assert actual == expected
    assert actual["ems_policy_source"] == "alpha20_cheapest_energy_safety_v1"


def test_planner_input_signature_is_stable_within_same_native_quarter() -> None:
    _install_stubs()
    multirate = importlib.import_module("custom_components.doems.ems_multirate")
    input_result = _input_result()

    first = multirate.planner_input_signature(
        input_result=input_result,
        settings=SETTINGS,
        soc_percent=50.0,
        reference=START + timedelta(seconds=1),
    )
    second = multirate.planner_input_signature(
        input_result=input_result,
        settings=SETTINGS,
        soc_percent=50.0,
        reference=START + timedelta(minutes=14, seconds=59),
    )
    assert first == second

    changed = _input_result()
    changed["rows"][5]["home_kwh"] = 0.251
    assert multirate.planner_input_signature(
        input_result=changed,
        settings=SETTINGS,
        soc_percent=50.0,
        reference=START,
    ) != first


def test_180_fast_ticks_cannot_enter_heavy_planner_path() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    tick_start = runtime.index("    def _execution_shadow_tick")
    tick_end = runtime.index("    @callback\n    def _schedule_planner_quarter_tick", tick_start)
    tick_block = runtime[tick_start:tick_end]
    assert 'self._request_fast_refresh("execution_shadow_monitor")' in tick_block
    assert "_request_planner_refresh" not in tick_block
    assert "_request_refresh" not in tick_block

    fast_start = runtime.index("    async def _async_fast_execution_refresh")
    fast_end = runtime.index("    def snapshot", fast_start)
    fast_block = runtime[fast_start:fast_end]
    assert "build_live_ems_input" not in fast_block
    assert "run_planner_worker" not in fast_block
    assert "async_add_executor_job" not in fast_block

    # 180 five-second ticks are 15 minutes.  All are classified fast-only.
    _install_stubs()
    multirate = importlib.import_module("custom_components.doems.ems_multirate")
    assert all(
        not multirate.is_planner_trigger("execution_shadow_monitor")
        for _ in range(180)
    )


def test_heavy_planner_is_executor_single_flight_with_generation_fence() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    assert "self._planner_task: asyncio.Task[None] | None = None" in runtime
    assert "self._planner_pending_triggers: set[str] = set()" in runtime
    assert "await self.hass.async_add_executor_job(worker)" in runtime

    compute = runtime.index("planner_result = await self.hass.async_add_executor_job(worker)")
    fence = runtime.index("if generation != self._planner_generation:", compute)
    publish = runtime.index("self.planner_result = planner_result", fence)
    assert compute < fence < publish
    assert "self._planner_stale_discard_count += 1" in runtime[fence:publish]


def test_native_quarter_and_meaningful_events_are_planner_triggers() -> None:
    _install_stubs()
    multirate = importlib.import_module("custom_components.doems.ems_multirate")
    for trigger in (
        "startup",
        "quarter_boundary",
        "energy_forecast_update",
        "solar_forecast_update",
        "prices_forecast_update",
        "soc_recovered",
    ):
        assert multirate.is_planner_trigger(trigger)

    for trigger in (
        "execution_shadow_monitor",
        "soc_state_change",
        "control_path_state_change",
        "plan_store_change",
        "manual_schedule_plan",
        "manual_cancel_plan",
        "automatic_execution_arm_change",
    ):
        assert not multirate.is_planner_trigger(trigger)
