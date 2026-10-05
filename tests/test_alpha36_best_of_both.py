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
START = datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)

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
    for package_name, path in (
        ("custom_components.doems.ems_alpha76", INTEGRATION / "ems_alpha76"),
        ("custom_components.doems.ems_alpha36", INTEGRATION / "ems_alpha36"),
    ):
        if package_name not in sys.modules:
            package = types.ModuleType(package_name)
            package.__path__ = [str(path)]
            sys.modules[package_name] = package

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


def _forecast(
    *,
    home: list[float] | None = None,
    solar: list[float] | None = None,
    prices: list[float] | None = None,
) -> list[dict]:
    home = home or [0.15] * 72
    solar = solar or [0.0] * 72
    prices = prices or [0.30] * 72
    rows = []
    for index in range(72):
        start = START + timedelta(hours=index)
        rows.append(
            {
                "time": start.isoformat(),
                "home_consumption_kwh": home[index],
                "solar_kwh": solar[index],
                "price": prices[index],
                "import_price": prices[index],
                "export_price": prices[index],
                "price_source": "test",
                "import_price_source": "test",
                "export_price_source": "test",
            }
        )
    return rows


def _run_policy(
    *,
    soc: float,
    home: list[float] | None = None,
    solar: list[float] | None = None,
    prices: list[float] | None = None,
    max_charge_power_w: int = 3200,
    commitments: list[dict] | None = None,
) -> tuple[dict, dict, dict]:
    _install_stubs()
    need_mod = importlib.import_module("custom_components.doems.ems_alpha36.energy_need")
    preview_mod = importlib.import_module("custom_components.doems.ems_alpha36.planner_preview")
    plan_mod = importlib.import_module("custom_components.doems.ems_alpha36.planner_72h")
    forecast = _forecast(home=home, solar=solar, prices=prices)
    need = need_mod.build_energy_need_analysis(forecast, soc, 7.0, now=START)
    preview = preview_mod.build_planner_preview(
        forecast,
        need,
        soc,
        92.0,
        92.0,
        0.10,
        max_charge_power_w=max_charge_power_w,
        max_discharge_power_w=3200,
        now=START,
    )
    plan = plan_mod.build_72h_plan_preview(
        forecast,
        need,
        preview,
        soc,
        92.0,
        92.0,
        execution_buffer_percent=2.0,
        max_charge_power_w=max_charge_power_w,
        max_discharge_power_w=3200,
        now=START,
        commitments=commitments or [],
    )
    return need, preview, plan


def _normalized_alpha80_sha(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace(
        "from ..const import",
        "from .const import",
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_alpha36_energy_need_and_preview_are_exact_alpha80_policy_ports() -> None:
    assert _normalized_alpha80_sha(INTEGRATION / "ems_alpha36" / "energy_need.py") == (
        "9d7dd824a0f9e5cb3835705326b4037b1ef45e9b549a17d138bb859cd99e9864"
    )
    assert _normalized_alpha80_sha(INTEGRATION / "ems_alpha36" / "planner_preview.py") == (
        "f7f453c6f48dd72514604e2367c69cdefc4fdadad6c7004d5f38647aecb3eb38"
    )


def test_low_solar_horizon_remains_planable() -> None:
    need, preview, plan = _run_policy(soc=80.0)
    assert need["energy_need_valid"] is True
    assert need["energy_need_first_usable_solar"] is None
    assert preview["planner_preview_safety_reserve_target_soc"] == 12.0
    assert plan["auto_plan_72h_count"] == 72


def test_later_cheaper_window_beats_earlier_window_when_reachable() -> None:
    home = [0.15] * 72
    prices = [0.34] * 72
    prices[6] = 0.20
    for index in range(18, 21):
        prices[index] = 0.10
    for index in range(21, 40):
        prices[index] = 0.45

    _need, preview, _plan = _run_policy(soc=60.0, home=home, prices=prices)
    selected = {item["time"] for item in preview["planner_preview_safety_charge_hours"]}
    assert (START + timedelta(hours=18)).isoformat() in selected
    assert (START + timedelta(hours=6)).isoformat() not in selected


def test_bridge_energy_is_bought_when_later_cheaper_window_is_not_safely_reachable() -> None:
    home = [0.25] * 72
    prices = [0.34] * 72
    prices[6] = 0.20
    prices[18] = 0.10

    _need, preview, _plan = _run_policy(soc=25.0, home=home, prices=prices)
    selected = {item["time"] for item in preview["planner_preview_safety_charge_hours"]}
    assert (START + timedelta(hours=6)).isoformat() in selected


def test_cheap_window_can_charge_near_full_for_later_demand() -> None:
    home = [0.05] * 72
    prices = [0.40] * 72
    for index in range(18, 21):
        prices[index] = 0.05
    for index in range(21, 31):
        home[index] = 0.60
        prices[index] = 0.48

    _need, preview, plan = _run_policy(soc=25.0, home=home, prices=prices)
    assert any(
        18 <= int(
            (datetime.fromisoformat(item["time"]) - START).total_seconds() // 3600
        ) <= 20
        for item in preview["planner_preview_safety_charge_hours"]
    )
    assert max(item["soc_end"] for item in plan["auto_plan_72h_plan"]) >= 98.0
    assert plan["auto_plan_72h_grid_safety_charge_kwh"] > 0.0


def test_alpha35_sequential_execution_reserve_invariant_remains_hard() -> None:
    home = [0.45] * 72
    solar = [0.0] * 72
    for index in {4, 5, 20, 21, 44, 45}:
        solar[index] = 0.90
    prices = [0.30] * 72
    for index in {1, 2, 6, 7, 8, 9, 12, 13}:
        prices[index] = 0.08

    _need, _preview, plan = _run_policy(
        soc=55.0,
        home=home,
        solar=solar,
        prices=prices,
    )
    assert plan["auto_plan_72h_valid"] is True
    assert plan["auto_plan_72h_execution_buffer_safe"] is True
    assert plan["auto_plan_72h_safety_plan_authority"] == (
        "doems_alpha38_split_reserve_safety_reachability_v1"
    )
    for row in plan["auto_plan_72h_plan"]:
        assert row["soc_end"] + 0.05 >= row["execution_reserve_floor_soc"]


def test_infeasible_execution_reserve_still_fails_closed() -> None:
    _need, _preview, plan = _run_policy(
        soc=10.0,
        home=[0.60] * 72,
        prices=[0.30] * 72,
        max_charge_power_w=0,
    )
    assert plan["auto_plan_72h_valid"] is False
    assert plan["auto_plan_72h_status"] == "infeasible"
    assert plan["auto_plan_72h_execution_buffer_safe"] is False


def test_production_worker_uses_alpha36_adapter_and_provenance() -> None:
    _install_stubs()
    adapter = importlib.import_module("custom_components.doems.ems_alpha36_adapter")
    multirate = importlib.import_module("custom_components.doems.ems_multirate")
    input_rows = []
    for index, row in enumerate(_forecast()):
        input_rows.append(
            {
                "start": row["time"],
                "home_kwh": row["home_consumption_kwh"],
                "solar_kwh": row["solar_kwh"],
                "solar_valid": True,
                "import_price": row["import_price"],
                "export_price": row["export_price"],
                "price_source": "test",
                "import_price_source": "test",
                "export_price_source": "test",
            }
        )
    input_result = {
        "status": "ready",
        "native_valid_slot_count": 288,
        "rows": input_rows,
        "time_contract": {"window_start": START.isoformat()},
    }
    expected = adapter.run_ems_chain(
        input_result=input_result,
        settings=SETTINGS,
        soc_percent=60.0,
        now=START,
    )
    actual = multirate.run_planner_worker(
        input_result=input_result,
        settings=SETTINGS,
        soc_percent=60.0,
        reference=START,
    )
    assert actual == expected
    assert actual["ems_policy_source"] == "alpha39_planstore_commitment_replay_v1"
    assert actual["economic_policy"] == "alpha80_cheapest_energy_safety_v1"
    assert actual["safety_authority"] == "doems_alpha38_split_reserve_safety_reachability_v1"


def test_runtime_queues_generation_only_after_signature_deduplication() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    request_start = runtime.index("    def _request_planner_refresh")
    request_end = runtime.index("    @callback\n    def _request_refresh", request_start)
    assert "_planner_generation +=" not in runtime[request_start:request_end]

    prepare_start = runtime.index("    async def _async_prepare_planner_requests")
    prepare_end = runtime.index("    async def _async_planner_loop", prepare_start)
    prepare = runtime[prepare_start:prepare_end]
    duplicate_check = prepare.index("signature == self._planner_active_signature")
    generation = prepare.index("self._planner_generation += 1")
    assert duplicate_check < generation
    assert "signature == pending_signature" in prepare


def test_runtime_has_start_critical_one_shot_and_preserves_fast_path() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    multirate = (INTEGRATION / "ems_multirate.py").read_text(encoding="utf-8")
    assert "def _planner_start_critical_key" in runtime
    assert 'self._request_planner_refresh("start_critical")' in runtime
    assert '"start_critical"' in multirate

    fast_start = runtime.index("    async def _async_fast_execution_refresh")
    fast_end = runtime.index("    def snapshot", fast_start)
    fast_block = runtime[fast_start:fast_end]
    assert "run_planner_worker" not in fast_block
    assert "async_add_executor_job" not in fast_block



def test_runtime_startup_queues_planner_without_awaiting_heavy_cycle() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    setup_start = runtime.index("    async def async_setup(self)")
    setup_end = runtime.index("    async def async_shutdown(self)", setup_start)
    setup = runtime[setup_start:setup_end]

    assert 'self._request_planner_refresh("startup")' in setup
    assert 'await self.async_refresh("startup")' not in setup
    assert setup.index('self._request_planner_refresh("startup")') < setup.index(
        "await self.physical_test.async_recover_if_needed()"
    )


def test_runtime_blocks_start_critical_during_first_startup_publication() -> None:
    runtime = (INTEGRATION / "ems_runtime.py").read_text(encoding="utf-8")
    init_start = runtime.index("    def __init__(")
    setup_start = runtime.index("    async def async_setup(self)", init_start)
    init = runtime[init_start:setup_start]
    assert "self._planner_startup_complete = False" in init

    guard_start = runtime.index("    def _request_start_critical_if_new")
    bridge_start = runtime.index(
        "    async def _async_run_bridge_planstore_scheduler", guard_start
    )
    guard = runtime[guard_start:bridge_start]
    assert "if not self._planner_startup_complete:" in guard

    compute_start = runtime.index("    async def _async_compute_planner_request")
    guard_fn_start = runtime.index("    def _planner_start_critical_key", compute_start)
    compute = runtime[compute_start:guard_fn_start]
    assert "self._planner_startup_complete = True" in compute


def test_alpha38_design_c_keeps_operational_reserve_fixed_while_safety_target_can_reach_full() -> None:
    home = [0.10] * 72
    solar = [0.0] * 72
    for index in range(10):
        home[index] = 0.80
    solar[10] = 1.20
    solar[11] = 1.20
    prices = [0.30] * 72
    prices[2] = 0.08
    prices[3] = 0.09

    _need, _preview, plan = _run_policy(
        soc=35.0,
        home=home,
        solar=solar,
        prices=prices,
    )
    rows = plan["auto_plan_72h_plan"]
    assert rows
    assert {row["reserve_floor_soc"] for row in rows} == {12.0}
    assert {row["execution_reserve_floor_soc"] for row in rows} == {12.0}
    assert max(row["safety_target_soc"] for row in rows) == 100.0
    assert max(row["precharge_protection_soc"] for row in rows) >= 12.0
    assert plan["auto_plan_72h_grid_safety_charge_kwh"] > 0.0
    assert plan["auto_plan_72h_reserve_policy"] == "fixed_operational_reserve_v1"
    assert plan["auto_plan_72h_safety_reachability_policy"] == (
        "split_reserve_safety_reachability_v1"
    )


def test_alpha38_design_c_keeps_future_safety_target_out_of_published_reserve() -> None:
    home = [0.15] * 72
    solar = [0.0] * 72
    for index in range(8):
        home[index] = 0.55
    solar[8] = 0.90
    solar[9] = 0.90

    _need, _preview, plan = _run_policy(
        soc=60.0,
        home=home,
        solar=solar,
        prices=[0.30] * 72,
    )
    assert plan["auto_plan_72h_reserve_floor_soc"] == 12.0
    assert plan["auto_plan_72h_dynamic_reserve_min_soc"] == 12.0
    assert plan["auto_plan_72h_dynamic_reserve_max_soc"] == 12.0
    assert any(row["safety_target_soc"] > 12.0 for row in plan["auto_plan_72h_plan"])


def test_alpha38_design_c_remains_observational_and_fail_closed() -> None:
    _need, _preview, plan = _run_policy(
        soc=10.0,
        home=[0.60] * 72,
        prices=[0.30] * 72,
        max_charge_power_w=0,
    )
    assert plan["auto_plan_72h_observational_only"] is True
    assert plan["auto_plan_72h_execution_enabled"] is False
    assert plan["auto_plan_72h_valid"] is False
    assert plan["auto_plan_72h_status"] == "infeasible"


def test_alpha39_manual_discharge_commitment_changes_soc_and_later_safety() -> None:
    commitment = {
        "slot": 1,
        "origin": "manual",
        "lifecycle_status": "pending",
        "commitment_kind": "manual_hard",
        "action": "ontladen",
        "start_time": (START + timedelta(hours=10)).isoformat(),
        "end_time": (START + timedelta(hours=12)).isoformat(),
        "power_w": 1000.0,
        "target_soc": 20.0,
        "planned_energy_kwh": 2.0,
    }
    _need, _preview, baseline = _run_policy(soc=80.0)
    _need, _preview, committed = _run_policy(soc=80.0, commitments=[commitment])
    base_rows = baseline["auto_plan_72h_plan"]
    rows = committed["auto_plan_72h_plan"]
    assert committed["auto_plan_72h_planstore_commitment_replay"] is True
    assert committed["auto_plan_72h_planstore_commitment_count"] == 1
    assert rows[10]["planstore_discharge_kwh"] > 0.0
    assert "planstore_ontladen" in rows[10]["action"]
    assert rows[11]["soc_end"] < base_rows[11]["soc_end"]


def test_alpha39_manual_charge_commitment_changes_soc_projection() -> None:
    commitment = {
        "slot": 2,
        "origin": "manual",
        "lifecycle_status": "pending",
        "commitment_kind": "manual_hard",
        "action": "laden",
        "start_time": (START + timedelta(hours=4)).isoformat(),
        "end_time": (START + timedelta(hours=5)).isoformat(),
        "power_w": 1200.0,
        "target_soc": 90.0,
        "planned_energy_kwh": 1.2,
    }
    _need, _preview, baseline = _run_policy(soc=40.0)
    _need, _preview, committed = _run_policy(soc=40.0, commitments=[commitment])
    assert committed["auto_plan_72h_plan"][4]["planstore_charge_kwh"] > 0.0
    assert committed["auto_plan_72h_plan"][4]["soc_end"] > baseline["auto_plan_72h_plan"][4]["soc_end"]
